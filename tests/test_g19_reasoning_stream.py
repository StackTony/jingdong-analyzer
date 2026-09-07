"""G19 红测：流式 reasoning_content 透传（AI 思考过程真流式显示）

现场根因（2026-09-07 铲屎官反馈「流式输出还是没有在 web 界面显示」）：
真实网关（euler-y / GLM-5.3-Flash）流式 delta 的 content 字段在思考阶段
全程为 None，思考内容在 `reasoning_content` 字段——G18 的 chat_stream
只透传 content，导致思考期间占位区空白，正文还要等生成完才到。

修法（三层）：
1. OpenAICompatibleProvider.chat_stream 改 yield (kind, text) 二元组：
   kind='reasoning'（思考）/ 'content'（正文）；base 默认回落改 yield
   ('content', chat()全文)
2. LLMReviewer.review_stream 的 on_delta 回调签名改 (kind, chunk)，
   返回值仍是正文全文（reasoning 不混入报告文本）
3. web 端思考过程灰色小字流式渲染 + 正文正常渲染
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.base import AIReviewer
from clowder_analytics.ai.llm_provider import (
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
)
from clowder_analytics.ai.llm_reviewer import LLMReviewer


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


def _chunk(reasoning=None, content=None):
    """构造一个流式 chunk mock（模拟 GLM 网关 delta 结构）"""
    c = MagicMock()
    c.choices = [MagicMock(delta=MagicMock(
        content=content, reasoning_content=reasoning,
    ))]
    return c


# ===== Provider 层：reasoning_content 透传 =====

def test_chat_stream_yields_reasoning_and_content_kinds():
    """chat_stream yield (kind, text)：思考阶段 reasoning_content，正文阶段 content"""
    p = OpenAICompatibleProvider(ProviderConfig(name="t", base_url="x", api_key="y", model="m"))
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = iter([
        _chunk(reasoning="The"),
        _chunk(reasoning=" user"),
        _chunk(content="## 异常解释"),
        _chunk(content="\n内容"),
    ])
    with patch("openai.OpenAI", return_value=fake_client):
        parts = list(p.chat_stream(messages=[{"role": "user", "content": "x"}]))
    assert parts == [
        ("reasoning", "The"),
        ("reasoning", " user"),
        ("content", "## 异常解释"),
        ("content", "\n内容"),
    ]


def test_chat_stream_base_fallback_yields_content_kind():
    """base 默认回落：非流式 chat 全文 yield ('content', full)"""
    class _ChatOnlyProvider(LLMProvider):
        def chat(self, messages, temperature=0.3, max_tokens=2000, response_format=None):
            return "一次性全文"

    parts = list(_ChatOnlyProvider().chat_stream([{"role": "user", "content": "x"}]))
    assert parts == [("content", "一次性全文")]


def test_chat_stream_delta_without_reasoning_attr():
    """标准 OpenAI delta（无 reasoning_content 字段）不炸——getattr 兜底 None"""
    p = OpenAICompatibleProvider(ProviderConfig(name="t", base_url="x", api_key="y", model="m"))
    fake_client = MagicMock()
    c = MagicMock()
    # delta 无 reasoning_content 属性（标准 OpenAI 兼容端点）
    delta = MagicMock(spec=["content"])
    delta.content = "hello"
    c.choices = [MagicMock(delta=delta)]
    fake_client.chat.completions.create.return_value = iter([c])
    with patch("openai.OpenAI", return_value=fake_client):
        parts = list(p.chat_stream(messages=[{"role": "user", "content": "x"}]))
    assert parts == [("content", "hello")]


# ===== Reviewer 层：on_delta 双段回调 =====

class _ReasoningStreamProvider(LLMProvider):
    """mock：先流 reasoning 再流 content（模拟 GLM 网关行为）"""

    def chat(self, messages, temperature=0.3, max_tokens=2000, response_format=None):
        return "正文"

    def chat_stream(self, messages, temperature=0.3, max_tokens=2000):
        yield ("reasoning", "思考1 ")
        yield ("reasoning", "思考2 ")
        yield ("content", "## 异常解释\n")
        yield ("content", "正文内容")


def test_llm_reviewer_review_stream_notifies_reasoning_and_content():
    """review_stream 的 on_delta 收 (kind, chunk)——思考段 + 正文段都通知"""
    df = pd.DataFrame({"brand": ["a"], "sales": [1]})
    ds = _make_dataset(df)
    reviewer = LLMReviewer(provider=_ReasoningStreamProvider())
    events: list[tuple[str, str]] = []
    out = reviewer.review_stream(ds, [], [], on_delta=lambda k, c: events.append((k, c)))
    # 返回值只含正文（reasoning 不混入报告）
    assert out == "## 异常解释\n正文内容"
    assert ("reasoning", "思考1 ") in events
    assert ("content", "## 异常解释\n") in events
    # 全事件序列
    assert events == [
        ("reasoning", "思考1 "), ("reasoning", "思考2 "),
        ("content", "## 异常解释\n"), ("content", "正文内容"),
    ]


def test_llm_reviewer_review_stream_no_delta_callback():
    """不传 on_delta 行为不变（返回正文全文）"""
    df = pd.DataFrame({"brand": ["a"], "sales": [1]})
    ds = _make_dataset(df)
    reviewer = LLMReviewer(provider=_ReasoningStreamProvider())
    out = reviewer.review_stream(ds, [], [])
    assert out == "## 异常解释\n正文内容"


# ===== run() 层：on_review_delta 双参数转发 =====

def test_run_forwards_kind_and_chunk_to_callback(tmp_path):
    """run(on_review_delta) 收 (kind, chunk) 二参——web 端按 kind 分流渲染"""
    from clowder_analytics.ai.fake import FakePlanGenerator
    from clowder_analytics.flow_library.store import FlowLibrary
    from clowder_analytics.orchestrator.run import run

    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    library = FlowLibrary(base_dir=tmp_path)

    class _Gen(FakePlanGenerator):
        def generate(self, question, dataset, intent=None):
            plan = super().generate(question, dataset, intent=intent)
            plan.reviewer_enabled = True
            return plan

    class _ReasoningReviewer(AIReviewer):
        def review(self, dataset, charts, run_log):
            return "正文"

        def review_stream(self, dataset, charts, run_log, on_delta=None):
            if on_delta:
                on_delta("reasoning", "思考中...")
                on_delta("content", "## 报告")
            return "## 报告"

    events: list[tuple[str, str]] = []
    result = run(
        question="Top10", dataset=ds, library=library,
        generator=_Gen(), reviewer=_ReasoningReviewer(),
        enable_review=True, on_review_delta=lambda k, c: events.append((k, c)),
    )
    assert events == [("reasoning", "思考中..."), ("content", "## 报告")]
    assert result.review == "## 报告"
