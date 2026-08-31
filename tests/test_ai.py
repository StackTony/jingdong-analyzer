"""F002 P3: AI Plan 生成器 + Reviewer 红测（spec §5.1 / §5.2）

FakePlanGenerator：按 intent 关键词路由到内置 Plan 模板
FakeReviewer：基于 run_log + 数据统计生成确定性三段式报告
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.base import AIPlanGenerator, AIReviewer
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.orchestrator.plan import Plan, Step


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


# ===== 抽象基类不可实例化 =====

def test_abstract_cannot_instantiate():
    with pytest.raises(TypeError):
        AIPlanGenerator()
    with pytest.raises(TypeError):
        AIReviewer()


# ===== FakePlanGenerator =====

def test_fake_generator_topn_intent():
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("Top30 品牌", ds, intent="TopN 趋势分析")
    assert isinstance(plan, Plan)
    assert plan.intent == "TopN 趋势分析"
    assert plan.schema_fingerprint == ds.schema_fingerprint
    # TopN plan 含 normalize → aggregate → topn
    op_names = [s.op for s in plan.steps]
    assert "model.topn" in op_names
    assert plan.fallback_strategy == "abort_on_first_error"


def test_fake_generator_anomaly_intent():
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [100, 200, 50]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("异常归因", ds, intent="异常归因")
    op_names = [s.op for s in plan.steps]
    assert "model.anomaly_attribution" in op_names


def test_fake_generator_correlation_intent():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("相关性分析", ds, intent="相关性分析")
    op_names = [s.op for s in plan.steps]
    assert "model.correlation" in op_names


def test_fake_generator_guesses_intent_when_none():
    """intent=None 时从 question 推断"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("找 Top30", ds, intent=None)
    assert plan.intent == "TopN 趋势分析"


def test_fake_generator_picks_value_col_by_hint():
    """从列名 hint 选 value_col（sales 优先）"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20], "price": [5, 8]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("Top10", ds, intent="TopN 趋势分析")
    # topn 步骤的 value_col 应为 sales
    topn_step = next(s for s in plan.steps if s.op == "model.topn")
    assert topn_step.args["value_col"] == "sales"


def test_fake_generator_picks_group_col_by_hint():
    """从列名 hint 选 group_by（brand 优先）"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("Top10", ds, intent="TopN 趋势分析")
    topn_step = next(s for s in plan.steps if s.op == "model.topn")
    assert topn_step.args["group_by"] == ["brand"]


def test_fake_generator_plan_id_auto_generated():
    """plan_id 自动生成（uuid）"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan1 = gen.generate("Top10", ds, intent="TopN 趋势分析")
    plan2 = gen.generate("Top10", ds, intent="TopN 趋势分析")
    assert plan1.plan_id != plan2.plan_id
    assert plan1.plan_id.startswith("fake-")


def test_fake_generator_plan_can_be_executed():
    """生成的 Plan 能被 P1.5 executor 跑通"""
    from clowder_analytics.orchestrator.executor import execute

    df = pd.DataFrame({"brand": ["a", "a", "b", "c"], "sales": [10, 20, 30, 40]})
    ds = _make_dataset(df)
    gen = FakePlanGenerator()
    plan = gen.generate("Top10", ds, intent="TopN 趋势分析")
    result = execute(plan, ds)
    # 全部步骤成功
    assert all(s["ok"] for s in result.log)
    assert len(result.charts) >= 1


# ===== FakeReviewer =====

def test_fake_reviewer_returns_three_section_markdown():
    """报告含三段：异常解释 / 趋势点睛 / 建议下一步"""
    df = pd.DataFrame({"brand": ["a", "b", "c", "d"], "sales": [100, 110, 50, 105]})
    ds = _make_dataset(df)
    reviewer = FakeReviewer()
    report = reviewer.review(ds, charts=[], run_log=[{"step": "x", "ok": True}])
    assert "## 异常解释" in report
    assert "## 趋势点睛" in report
    assert "## 建议下一步" in report


def test_fake_reviewer_detects_outlier():
    """含异常值时报告应提到异常"""
    df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [100, 110, 9999]})
    ds = _make_dataset(df)
    reviewer = FakeReviewer()
    report = reviewer.review(ds, charts=[], run_log=[])
    assert "异常" in report or "偏高" in report or "偏低" in report


def test_fake_reviewer_no_outlier():
    """无异常值时报告应说明"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [100, 110]})
    ds = _make_dataset(df)
    reviewer = FakeReviewer()
    report = reviewer.review(ds, charts=[], run_log=[])
    assert "异常" in report or "未检测到" in report


def test_fake_reviewer_includes_run_log_summary():
    """报告应包含 run_log 概要"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    reviewer = FakeReviewer()
    run_log = [
        {"step": "clean.x", "ok": True},
        {"step": "model.y", "ok": False, "err": "boom"},
    ]
    report = reviewer.review(ds, charts=[], run_log=run_log)
    assert "1 步成功" in report
    assert "1 步失败" in report


def test_fake_reviewer_suggests_correlation_when_multiple_numeric():
    """≥2 个数值列时建议相关性分析"""
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "brand": ["x", "y"]})
    ds = _make_dataset(df)
    reviewer = FakeReviewer()
    report = reviewer.review(ds, charts=[], run_log=[])
    assert "相关" in report


# ===== 端到端：fallback → generate → execute → review =====

def test_end_to_end_fallback_generate_execute_review():
    """fallback → FakeGenerator 生成 Plan → execute → FakeReviewer 出报告"""
    from clowder_analytics.orchestrator.executor import execute

    df = pd.DataFrame({"brand": ["小米", "华为", "OPPO", "vivo"], "sales": [100, 200, 250, 50]})
    ds = _make_dataset(df)

    # 1. fallback 生成
    gen = FakePlanGenerator()
    plan = gen.generate("Top30 品牌", ds, intent="TopN 趋势分析")

    # 2. 执行
    result = execute(plan, ds)
    assert all(s["ok"] for s in result.log)

    # 3. Reviewer 报告
    reviewer = FakeReviewer()
    report = reviewer.review(ds, charts=result.charts, run_log=result.log)
    assert "## 异常解释" in report
    assert "## 趋势点睛" in report
    assert "## 建议下一步" in report
