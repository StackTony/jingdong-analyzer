"""F002 P1.5: Plan 执行器红测（spec §6.2 / ADR-0001 D10）

在调 LLM 前先验证"Plan + op + 执行器"链路通。
用固定 Plan 跑端到端：读 CSV → 标准化品牌 → 聚合 → TopN。
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.atomic.spec import ChartSpec
from clowder_analytics.orchestrator.executor import execute
from clowder_analytics.orchestrator.plan import OpError, Plan, RunResult, Step


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(
        df=df,
        schema_fingerprint=compute_fingerprint(df),
        source_type="memory",
    )


# ===== execute 基础 =====

def test_execute_single_clean_op():
    """单步 clean op 跑通"""
    df = pd.DataFrame({"brand": ["a", "a", "b"], "sales": [10, 20, 30]})
    plan = Plan(
        plan_id="t1",
        intent="测试",
        steps=[Step(op="clean.remove_duplicates", args={"keys": ["brand"], "keep": "first"})],
    )
    result = execute(plan, _make_dataset(df))
    assert isinstance(result, RunResult)
    assert len(result.df) == 2
    assert len(result.log) == 1
    assert result.log[0]["ok"] is True
    assert "removed" in result.log[0]["report"]
    assert result.route == "B"
    assert result.plan_id == "t1"


def test_execute_multi_step_chain():
    """多步链：normalize → aggregate → topn"""
    df = pd.DataFrame({
        "brand": ["  A  ", "a", "  B "],
        "sales": [10, 20, 30],
    })
    plan = Plan(
        plan_id="t2",
        intent="TopN 趋势分析",
        steps=[
            Step(op="clean.normalize_text", args={"columns": ["brand"], "ops": ["trim", "lower"]}),
            Step(op="model.aggregate", args={"group_by": ["brand"], "agg": {"sales": "sum"}}),
            Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 5, "rank_by": "value"}),
        ],
    )
    result = execute(plan, _make_dataset(df))
    assert len(result.log) == 3
    assert all(s["ok"] for s in result.log)
    # 标准化后 a/a 合并，b 独立
    assert len(result.df) == 2
    # topn chart_spec 应被收集
    assert len(result.charts) >= 1
    assert isinstance(result.charts[0], ChartSpec)


def test_execute_collects_chart_specs_from_model_ops():
    """model op 输出的 ChartSpec 应收集到 result.charts"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    plan = Plan(
        plan_id="t3",
        intent="测试",
        steps=[
            Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 2, "rank_by": "value"}),
        ],
    )
    result = execute(plan, _make_dataset(df))
    assert len(result.charts) == 1
    assert result.charts[0].type == "bar"


def test_execute_no_charts_when_only_clean_ops():
    """纯 clean op 不产 chart"""
    df = pd.DataFrame({"brand": ["a", "a"], "sales": [10, 20]})
    plan = Plan(
        plan_id="t4",
        intent="测试",
        steps=[Step(op="clean.remove_duplicates", args={"keys": ["brand"], "keep": "first"})],
    )
    result = execute(plan, _make_dataset(df))
    assert len(result.charts) == 0


# ===== OpError 与 fallback_strategy =====

def test_execute_unknown_op_raises_operror():
    """未知 op 应抛 OpError 并记录 log"""
    df = pd.DataFrame({"a": [1]})
    plan = Plan(
        plan_id="t5",
        intent="测试",
        steps=[Step(op="clean.nonexistent_op", args={})],
    )
    result = execute(plan, _make_dataset(df))
    assert result.log[0]["ok"] is False
    assert "err" in result.log[0]
    # 默认 fallback_strategy=abort，df 不变


def test_execute_abort_on_first_error():
    """fallback=abort_on_first_error：失败后停止后续步骤"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    plan = Plan(
        plan_id="t6",
        intent="测试",
        steps=[
            Step(op="clean.nonexistent_op", args={}),
            Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 2, "rank_by": "value"}),
        ],
        fallback_strategy="abort_on_first_error",
    )
    result = execute(plan, _make_dataset(df))
    # 第一步失败，第二步不应执行
    assert len(result.log) == 1
    assert result.log[0]["ok"] is False


def test_execute_continue_on_error():
    """fallback=continue_on_error：失败后继续下一步"""
    df = pd.DataFrame({"brand": ["a", "b"], "sales": [10, 20]})
    plan = Plan(
        plan_id="t7",
        intent="测试",
        steps=[
            Step(op="clean.nonexistent_op", args={}),
            Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 2, "rank_by": "value"}),
        ],
        fallback_strategy="continue_on_error",
    )
    result = execute(plan, _make_dataset(df))
    assert len(result.log) == 2
    assert result.log[0]["ok"] is False
    assert result.log[1]["ok"] is True


def test_execute_op_args_error_caught_as_operror():
    """op 执行抛 ValueError（如未知 strategy）应被包装为 OpError"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    plan = Plan(
        plan_id="t8",
        intent="测试",
        steps=[
            Step(op="clean.fill_missing", args={"columns": ["sales"], "strategy": "nonexistent_strategy"}),
        ],
    )
    result = execute(plan, _make_dataset(df))
    assert result.log[0]["ok"] is False
    assert "err" in result.log[0]


# ===== Plan 数据类 round-trip =====

def test_plan_from_dict_round_trip():
    """Plan from_dict 正确解析 spec §5.1 JSON 结构"""
    plan_dict = {
        "plan_id": "abc-123",
        "intent": "TopN 趋势分析",
        "schema_fingerprint": "fp123",
        "steps": [
            {"op": "clean.normalize_text", "args": {"columns": ["brand"], "ops": ["trim"]}},
            {"op": "model.topn", "args": {"group_by": ["brand"], "value_col": "sales", "n": 30, "rank_by": "value"}},
        ],
        "reviewer_enabled": True,
        "fallback_strategy": "continue_on_error",
    }
    plan = Plan.from_dict(plan_dict)
    assert plan.plan_id == "abc-123"
    assert plan.intent == "TopN 趋势分析"
    assert plan.schema_fingerprint == "fp123"
    assert len(plan.steps) == 2
    assert plan.steps[0].op == "clean.normalize_text"
    assert plan.steps[0].args["columns"] == ["brand"]
    assert plan.reviewer_enabled is True
    assert plan.fallback_strategy == "continue_on_error"


def test_step_from_dict_default_args():
    """Step from_dict 缺 args 字段时默认空 dict"""
    step = Step.from_dict({"op": "clean.remove_duplicates"})
    assert step.op == "clean.remove_duplicates"
    assert step.args == {}


# ===== 端到端 fixed Plan =====

def test_end_to_end_fixed_plan_topn():
    """端到端：固定 Plan 用 P1 原子能力跑通 TopN 分析

    场景：品牌销量 TopN
    步骤：去重 → 标准化品牌 → 聚合 → TopN
    断言：最终 df 是 TopN 结果，charts 含 bar 图
    """
    df = pd.DataFrame({
        "brand": ["小米", "小米", "华为", "OPPO", "vivo"],
        "sales": [100, 200, 300, 250, 180],
    })
    plan = Plan(
        plan_id="e2e-topn-001",
        intent="TopN 趋势分析",
        steps=[
            Step(op="clean.remove_duplicates", args={"keys": ["brand"], "keep": "first"}),
            Step(op="model.aggregate", args={"group_by": ["brand"], "agg": {"sales": "sum"}}),
            Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 3, "rank_by": "value"}),
        ],
        fallback_strategy="abort_on_first_error",
    )
    result = execute(plan, _make_dataset(df))

    # 全部步骤成功
    assert len(result.log) == 3
    assert all(s["ok"] for s in result.log)

    # TopN=3，返回 3 行
    assert len(result.df) == 3
    # 降序：华为(300) > OPPO(250) > vivo(180)
    assert result.df["sales"].tolist() == [300, 250, 180]

    # 两个 model op 各产一个 chart（aggregate + topn）
    assert len(result.charts) == 2
    assert all(c.type == "bar" for c in result.charts)

    # route 默认 B，review P1.5 不接
    assert result.route == "B"
    assert result.review is None
    assert result.plan_id == "e2e-topn-001"


def test_end_to_end_anomaly_attribution():
    """端到端：异常归因 Plan"""
    df = pd.DataFrame({
        "brand": ["a", "b", "c", "d"],
        "sales": [100, 110, 50, 105],  # c 是异常低
    })
    plan = Plan(
        plan_id="e2e-anomaly-001",
        intent="异常归因",
        steps=[
            Step(op="model.anomaly_attribution", args={
                "value_col": "sales", "group_by": ["brand"], "baseline": "mean",
            }),
        ],
    )
    result = execute(plan, _make_dataset(df))
    assert result.log[0]["ok"] is True
    assert "deviation" in result.df.columns
    assert len(result.charts) == 1
