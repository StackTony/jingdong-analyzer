"""F002 P4: 端到端 run() 入口红测

run() 把 P1.5 executor + P2 router + P3 generator/reviewer + P4 promoter 串起来：
question + source → route → execute → review → save_run → scan_promote

测试三种 route：
- A 轨：library 已有 stable template
- B 轨：library 已有 plan
- fallback：无匹配，FakeGenerator 生成
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.plan import Plan, Step
from clowder_analytics.orchestrator.run import run
from clowder_analytics.flow_library.models import Template


@pytest.fixture
def library(tmp_path):
    return FlowLibrary(base_dir=tmp_path)


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


def test_run_fallback_generates_plan_and_executes(library):
    """A/B 都无命中 → fallback → FakeGenerator 生成 → execute → 沉淀 RunRecord"""
    df = pd.DataFrame({"brand": ["小米", "华为", "OPPO"], "sales": [100, 200, 250]})
    ds = _make_dataset(df)

    result = run(
        question="Top30 品牌",
        dataset=ds,
        library=library,
        generator=FakePlanGenerator(),
        reviewer=FakeReviewer(),
    )
    assert result.route == "fallback"
    assert result.plan_id  # 生成的 plan 有 id
    assert all(s["ok"] for s in result.log)
    # RunRecord 已沉淀
    runs = library.list_runs()
    assert len(runs) == 1
    assert runs[0].route == "fallback"
    assert runs[0].matched_plan_id == result.plan_id
    # fallback 调了一次 LLM（FakeGenerator 计为 1）
    assert runs[0].llm_calls == 1


def test_run_a_track_uses_template(library):
    """A 轨命中：用 template 的 steps 执行"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)
    library.save_template(Template(
        template_id="t_stable",
        intent="TopN 趋势分析",
        schema_fingerprint=ds.schema_fingerprint,
        steps=[Step(op="model.topn", args={
            "group_by": ["brand"], "value_col": "sales", "n": 3, "rank_by": "value",
        })],
        stability="stable", confidence=0.9,
    ))

    result = run("Top10 品牌", ds, library=library,
                 generator=FakePlanGenerator(), reviewer=FakeReviewer())
    assert result.route == "A"
    assert result.matched_template_id == "t_stable"
    # A 轨 0 LLM 调用
    runs = library.list_runs()
    assert runs[0].llm_calls == 0
    assert runs[0].matched_template_id == "t_stable"


def test_run_b_track_uses_plan(library):
    """B 轨命中：用 plan 的 steps 执行"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    library.save_plan(Plan(
        plan_id="p_b",
        intent="TopN 趋势分析",
        schema_fingerprint=ds.schema_fingerprint,
        steps=[Step(op="model.topn", args={
            "group_by": ["brand"], "value_col": "sales", "n": 2, "rank_by": "value",
        })],
    ))

    result = run("Top10", ds, library=library,
                 generator=FakePlanGenerator(), reviewer=FakeReviewer())
    assert result.route == "B"
    assert result.matched_plan_id == "p_b"
    runs = library.list_runs()
    assert runs[0].llm_calls == 0
    assert runs[0].matched_plan_id == "p_b"


def test_run_with_reviewer_enabled(library):
    """plan.reviewer_enabled=True 或 run 参数 enable_review=True 时调 Reviewer"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [100, 200, 50]})
    ds = _make_dataset(df)
    library.save_template(Template(
        template_id="t",
        intent="异常归因",
        schema_fingerprint=ds.schema_fingerprint,
        steps=[Step(op="model.anomaly_attribution", args={
            "value_col": "sales", "group_by": ["brand"], "baseline": "mean",
        })],
        stability="stable", confidence=0.9,
        reviewer_enabled=True,
    ))
    result = run("哪些品牌销量异常", ds, library=library,
                 generator=FakePlanGenerator(), reviewer=FakeReviewer())
    assert result.review is not None
    assert "## 异常解释" in result.review


def test_run_no_review_when_disabled(library):
    """reviewer_enabled=False 时 review 为 None"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    result = run("Top10", ds, library=library,
                 generator=FakePlanGenerator(), reviewer=FakeReviewer(),
                 enable_review=False)
    assert result.review is None


def test_run_fallback_plan_saved_to_library(library):
    """fallback 生成的 Plan 沉淀到 plans/ 供下次复用"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)
    result = run("Top30", ds, library=library,
                 generator=FakePlanGenerator(), reviewer=FakeReviewer())
    saved_plan = library.load_plan(result.plan_id)
    assert saved_plan is not None
    assert saved_plan.intent == "TopN 趋势分析"
    assert saved_plan.schema_fingerprint == ds.schema_fingerprint


def test_run_fallback_then_b_track_on_second_call(library):
    """第一次 fallback 生成 + 沉淀，第二次同 question 应走 B 轨复用"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)

    # 第一次 fallback
    r1 = run("Top30", ds, library=library,
             generator=FakePlanGenerator(), reviewer=FakeReviewer())
    assert r1.route == "fallback"
    assert r1.llm_calls == 1

    # 第二次同 question → B 轨命中
    r2 = run("Top30", ds, library=library,
             generator=FakePlanGenerator(), reviewer=FakeReviewer())
    assert r2.route == "B"
    assert r2.matched_plan_id == r1.plan_id
    assert r2.llm_calls == 0  # 复用，不调 LLM


def test_run_auto_promote_after_three_successes(library):
    """fallback 3 次成功后自动晋升 candidate"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)

    for _ in range(3):
        run("Top30", ds, library=library,
            generator=FakePlanGenerator(), reviewer=FakeReviewer())

    # 检查 library 应有 candidate template
    templates = library.list_templates()
    assert len(templates) == 1
    assert templates[0].stability == "candidate"
    assert templates[0].promoted_from_plan_id is not None


def test_run_logs_failed_steps_in_run_record(library):
    """执行有失败时 RunRecord.success=False 并记录 steps 概要"""
    # 故意构造一个会让 op 失败的 Plan（未知 op）
    df = pd.DataFrame({"a": [1]})
    ds = _make_dataset(df)
    library.save_plan(Plan(
        plan_id="p_fail",
        intent="TopN 趋势分析",
        schema_fingerprint=ds.schema_fingerprint,
        steps=[Step(op="clean.nonexistent_op", args={})],
    ))
    result = run("Top10", ds, library=library,
                 generator=FakePlanGenerator(), reviewer=FakeReviewer())
    assert result.route == "B"
    runs = library.list_runs()
    assert runs[0].success is False
