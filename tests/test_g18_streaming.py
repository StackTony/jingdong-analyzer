"""G18 红测：AI Reviewer 流式输出（用户不再死等）

需求（铲屎官 2026-09-05）：「AI reviewer的AI思考过程也可以展示出来，
可以流式输出，不然用户一直在等待」

三层流式链路：
1. LLMProvider.chat_stream(messages, ...) -> Iterator[str]（base 默认回落 chat()）
2. AIReviewer.review_stream(dataset, charts, run_log, on_delta) -> str
   （base 默认回落 review()，不传 on_delta 行为与 review() 一致）
3. run() 接受可选 on_review_delta 回调转发给 reviewer
"""
from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.base import AIReviewer
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.ai.llm_provider import (
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
)
from clowder_analytics.ai.llm_reviewer import LLMReviewer
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.run import run


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


class _StreamMockProvider(LLMProvider):
    """确定性 mock：chat_stream 按预设 chunk 流式 yield"""

    def __init__(self, chunks: list[str]):
        self.chunks = chunks
        self.last_stream_messages: list[dict] | None = None

    def chat(self, messages, temperature=0.3, max_tokens=2000, response_format=None):
        return "".join(self.chunks)

    def chat_stream(self, messages, temperature=0.3, max_tokens=2000):
        self.last_stream_messages = messages
        yield from self.chunks


# ===== Provider 层 =====

def test_provider_chat_stream_base_falls_back_to_chat():
    """base LLMProvider.chat_stream 默认实现：非流式 chat 一次性 yield"""
    class _NoStreamProvider(LLMProvider):
        def chat(self, messages, temperature=0.3, max_tokens=2000, response_format=None):
            return "full text"

    p = _NoStreamProvider()
    chunks = list(p.chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == ["full text"]


def test_openai_provider_chat_stream_yields_chunks():
    """OpenAICompatibleProvider.chat_stream 用 stream=True 逐 chunk yield"""
    config = ProviderConfig(name="t", base_url="x", api_key="y", model="m")
    p = OpenAICompatibleProvider(config)

    fake_client = MagicMock()
    chunk1, chunk2, chunk3 = MagicMock(), MagicMock(), MagicMock()
    chunk1.choices = [MagicMock(delta=MagicMock(content="## 异常"))]
    chunk2.choices = [MagicMock(delta=MagicMock(content="解释\n"))]
    chunk3.choices = [MagicMock(delta=MagicMock(content="## 趋势"))]
    fake_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk3])

    with patch("openai.OpenAI", return_value=fake_client):
        chunks = list(p.chat_stream(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.4, max_tokens=1500,
        ))
    assert chunks == ["## 异常", "解释\n", "## 趋势"]
    create_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert create_kwargs["stream"] is True
    assert create_kwargs["max_tokens"] == 1500


def test_openai_provider_chat_stream_empty_delta_skipped():
    """空 delta chunk（如 role 首块 / usage 尾块）跳过不 yield"""
    config = ProviderConfig(name="t", base_url="x", api_key="y", model="m")
    p = OpenAICompatibleProvider(config)
    fake_client = MagicMock()
    c_role = MagicMock()
    c_role.choices = [MagicMock(delta=MagicMock(content=None))]
    c_text = MagicMock()
    c_text.choices = [MagicMock(delta=MagicMock(content="abc"))]
    fake_client.chat.completions.create.return_value = iter([c_role, c_text])
    with patch("openai.OpenAI", return_value=fake_client):
        chunks = list(p.chat_stream(messages=[{"role": "user", "content": "x"}]))
    assert chunks == ["abc"]


# ===== Reviewer 层 =====

def test_reviewer_review_stream_base_falls_back_to_review():
    """base AIReviewer.review_stream 默认实现：回落 review()，on_delta 只调一次"""
    class _LegacyReviewer(AIReviewer):
        def review(self, dataset, charts, run_log):
            return "## 报告"

    df = pd.DataFrame({"a": [1]})
    ds = _make_dataset(df)
    r = _LegacyReviewer()
    deltas: list[str] = []
    out = r.review_stream(ds, [], [], on_delta=deltas.append)
    assert out == "## 报告"
    assert deltas == ["## 报告"]


def test_llm_reviewer_review_stream_accumulates_and_notifies():
    """LLMReviewer.review_stream：流式 chunk 累积成全文 + on_delta 逐块通知"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [1, 2]})
    ds = _make_dataset(df)
    mock = _StreamMockProvider(["## 异常解释\n", "内容A\n", "## 建议下一步"])
    reviewer = LLMReviewer(provider=mock)
    deltas: list[str] = []
    out = reviewer.review_stream(ds, [], [], on_delta=deltas.append)
    assert out == "## 异常解释\n内容A\n## 建议下一步"
    assert deltas == ["## 异常解释\n", "内容A\n", "## 建议下一步"]
    # prompt 与 review() 同构（system + user）
    assert mock.last_stream_messages[0]["role"] == "system"
    assert "brand" in mock.last_stream_messages[1]["content"]


def test_llm_reviewer_review_stream_without_delta():
    """不传 on_delta 时 review_stream 行为等同 review()"""
    df = pd.DataFrame({"brand": ["a"], "sales": [1]})
    ds = _make_dataset(df)
    mock = _StreamMockProvider(["报告全文"])
    reviewer = LLMReviewer(provider=mock)
    out = reviewer.review_stream(ds, [], [])
    assert out == "报告全文"


def test_llm_reviewer_review_stream_provider_without_stream_support():
    """provider 只有 chat()（如 MockProvider）时 review_stream 回落 chat 一次性返回"""
    class _ChatOnlyProvider(LLMProvider):
        def chat(self, messages, temperature=0.3, max_tokens=2000, response_format=None):
            return "一次性全文"

    df = pd.DataFrame({"a": [1]})
    ds = _make_dataset(df)
    reviewer = LLMReviewer(provider=_ChatOnlyProvider())
    deltas: list[str] = []
    out = reviewer.review_stream(ds, [], [], on_delta=deltas.append)
    assert out == "一次性全文"
    assert deltas == ["一次性全文"]


# ===== run() 层 =====

def test_run_forwards_on_review_delta():
    """run(on_review_delta=...) 转发给 reviewer.review_stream"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=_tmp_lib_dir())

    class _StreamReviewer(AIReviewer):
        def __init__(self):
            self.review_called = False

        def review(self, dataset, charts, run_log):
            return "全文"

        def review_stream(self, dataset, charts, run_log, on_delta=None):
            self.review_called = True
            if on_delta:
                on_delta("chunk1 ")
                on_delta("chunk2")
            return "chunk1 chunk2"

    class _RevEnabledGenerator(FakePlanGenerator):
        """生成 reviewer_enabled=True 的 plan（Fake 默认 False 不触发 review）"""
        def generate(self, question, dataset, intent=None):
            from clowder_analytics.orchestrator.plan import Plan, Step
            from clowder_analytics.ai.fake import FakePlanGenerator as _F
            plan = super().generate(question, dataset, intent=intent)
            plan.reviewer_enabled = True
            return plan

    reviewer = _StreamReviewer()
    deltas: list[str] = []
    result = run(
        question="Top10 品牌",
        dataset=ds,
        library=library,
        generator=_RevEnabledGenerator(),
        reviewer=reviewer,
        enable_review=True,
        on_review_delta=deltas.append,
    )
    assert reviewer.review_called is True
    assert deltas == ["chunk1 ", "chunk2"]
    assert result.review == "chunk1 chunk2"


def test_run_review_delta_not_fired_when_review_disabled():
    """enable_review=False 时 on_review_delta 不被调用"""
    df = pd.DataFrame({"brand": ["a"], "sales": [1]})
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=_tmp_lib_dir())
    deltas: list[str] = []
    result = run(
        question="Top10",
        dataset=ds,
        library=library,
        reviewer=FakeReviewer(),
        enable_review=False,
        on_review_delta=deltas.append,
    )
    assert deltas == []
    assert result.review is None


def _tmp_lib_dir():
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp(prefix="g18-lib-"))
    return d


# ===== 铲屎官补充（2026-09-05）：reviewer 调用也消耗 token，计入 llm_calls =====

def test_run_counts_reviewer_call_in_llm_calls(tmp_path):
    """reviewer 实际被调时 llm_calls +1——AI 报告生成也是一次 LLM 调用"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=tmp_path)

    class _RevEnabledGenerator(FakePlanGenerator):
        def generate(self, question, dataset, intent=None):
            plan = super().generate(question, dataset, intent=intent)
            plan.reviewer_enabled = True
            return plan

    result = run(
        question="Top10",
        dataset=ds,
        library=library,
        generator=_RevEnabledGenerator(),
        reviewer=FakeReviewer(),
        enable_review=True,
    )
    assert result.review is not None
    # fallback 生成 plan（1）+ reviewer 调用（1）= 2
    assert result.llm_calls == 2


def test_run_reviewer_not_called_no_llm_calls_bump(tmp_path):
    """enable_review=False 时 reviewer 不调，llm_calls 不 bump"""
    df = pd.DataFrame({"brand": ["a"], "sales": [1]})
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=tmp_path)

    class _RevEnabledGenerator(FakePlanGenerator):
        def generate(self, question, dataset, intent=None):
            plan = super().generate(question, dataset, intent=intent)
            plan.reviewer_enabled = True
            return plan

    result = run(
        question="Top10",
        dataset=ds,
        library=library,
        generator=_RevEnabledGenerator(),
        reviewer=FakeReviewer(),
        enable_review=False,
    )
    assert result.review is None
    assert result.llm_calls == 1  # 只有 fallback 生成 plan


def test_run_a_track_with_reviewer_counts_one_llm_call(tmp_path):
    """A 轨命中（无 fallback）+ reviewer 开启：llm_calls = 1（只有 reviewer）"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [100, 200, 50]})
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=tmp_path)
    from clowder_analytics.flow_library.models import Template
    from clowder_analytics.orchestrator.plan import Step

    library.save_template(Template(
        template_id="t-anomaly",
        intent="异常归因",
        schema_fingerprint=ds.schema_fingerprint,
        steps=[Step(op="model.anomaly_attribution", args={
            "value_col": "sales", "group_by": ["brand"], "baseline": "mean",
        })],
        stability="stable", confidence=0.9,
        reviewer_enabled=True,
    ))
    result = run(
        "哪些品牌销量异常", ds, library=library,
        generator=FakePlanGenerator(), reviewer=FakeReviewer(),
    )
    assert result.route == "A"
    assert result.review is not None
    assert result.llm_calls == 1  # 只有 reviewer 这一次
