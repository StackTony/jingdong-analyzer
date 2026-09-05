"""G18 红测：执行过程信息增强（命中模板输出太少）

需求（铲屎官 2026-09-05）：「命中模板的执行过程还是输出太少」

executor run_log 每步 entry 增强：
- args：本步使用的参数（列名等）——用户要看到"用了哪些列"
- shape_before / shape_after：数据形态变化（如 aggregate 33万行 → 20行）
- model 步 report 含图表 title/x/y 维度（不只 chart type 一个字符串）

web _step_detail 增强渲染这些新字段。
"""
from __future__ import annotations

import pandas as pd

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.orchestrator.executor import execute
from clowder_analytics.orchestrator.plan import Plan, Step


def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


# ===== executor：args + shape =====

def test_execute_log_entry_contains_args():
    """每步 entry 记录 args——用户能看到该步用了哪些列/参数"""
    df = pd.DataFrame({
        "brand": ["a", "b", "a", "c"],
        "sales": [10, 20, 30, 40],
    })
    ds = _make_dataset(df)
    plan = Plan(plan_id="p1", intent="TopN 趋势分析", steps=[
        Step(op="clean.remove_duplicates", args={"keys": ["brand"]}),
    ])
    result = execute(plan, ds)
    assert result.log[0]["args"] == {"keys": ["brand"]}


def test_execute_log_entry_contains_shape_before_after():
    """每步 entry 记录 shape_before / shape_after——数据形态变化可见"""
    df = pd.DataFrame({
        "brand": ["a", "b", "a", "c"],
        "sales": [10, 20, 30, 40],
    })
    ds = _make_dataset(df)
    plan = Plan(plan_id="p1", intent="TopN 趋势分析", steps=[
        Step(op="clean.remove_duplicates", args={"keys": ["brand"]}),
        Step(op="model.aggregate", args={"group_by": "brand", "agg": {"sales": "sum"}}),
    ])
    result = execute(plan, ds)
    # drop_duplicates: 4行2列 → 3行2列
    assert result.log[0]["shape_before"] == (4, 2)
    assert result.log[0]["shape_after"] == (3, 2)
    # aggregate: 3行2列 → 3行2列（group 数）
    assert result.log[1]["shape_before"] == (3, 2)
    assert result.log[1]["shape_after"][0] == 3  # 3 个 brand 分组


def test_execute_log_shape_present_on_failed_step():
    """失败步也记录 shape_before（after 为 None 或缺省）"""
    df = pd.DataFrame({"brand": ["a"], "sales": [1]})
    ds = _make_dataset(df)
    plan = Plan(plan_id="p1", intent="TopN 趋势分析", steps=[
        Step(op="model.aggregate", args={"group_by": "nonexistent", "agg": {"sales": "sum"}}),
    ], fallback_strategy="continue_on_error")
    result = execute(plan, ds)
    assert result.log[0]["ok"] is False
    assert result.log[0]["shape_before"] == (1, 2)


def test_execute_log_model_step_report_includes_chart_details():
    """model 步 report 含 chart title/x/y 维度——不只一个 type 字符串"""
    df = pd.DataFrame({
        "brand": ["a", "b", "c"],
        "sales": [10, 20, 30],
    })
    ds = _make_dataset(df)
    plan = Plan(plan_id="p1", intent="TopN 趋势分析", steps=[
        Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 3}),
    ])
    result = execute(plan, ds)
    model_entry = result.log[0]
    report = model_entry["report"]
    assert report["chart_spec"] == "bar"
    assert report["title"] == "Top 3 by sales"
    assert report["x"] == "brand"
    assert report["y"] == "sales"


# ===== web 渲染增强 =====

def test_step_detail_shows_args():
    """_step_detail 渲染 args（用到的列）"""
    from clowder_analytics.web.app import _step_detail
    entry = {
        "step": "model.aggregate", "ok": True,
        "args": {"group_by": "brand", "agg": {"sales": "sum"}},
        "shape_before": (330000, 5), "shape_after": (20, 2),
        "report": {"chart_spec": None},
    }
    detail = _step_detail(entry)
    assert "brand" in detail
    assert "sales" in detail


def test_step_detail_shows_shape_change():
    """_step_detail 渲染 shape 变化（330000行 → 20行）"""
    from clowder_analytics.web.app import _step_detail
    entry = {
        "step": "model.aggregate", "ok": True,
        "args": {"group_by": "brand"},
        "shape_before": (330000, 5), "shape_after": (20, 2),
        "report": {},
    }
    detail = _step_detail(entry)
    assert "330000" in detail
    assert "20" in detail


def test_step_detail_chart_report_shows_dimensions():
    """chart report 渲染 title/x/y 维度"""
    from clowder_analytics.web.app import _step_detail
    entry = {
        "step": "model.bar", "ok": True,
        "args": {"x": "brand", "y": "sales", "title": "品牌销量"},
        "report": {"chart_spec": "bar", "title": "品牌销量", "x": "brand", "y": "sales"},
    }
    detail = _step_detail(entry)
    assert "品牌销量" in detail
    assert "brand" in detail


def test_step_detail_backward_compat_old_entries():
    """旧格式 entry（无 args/shape，report 只有 chart_spec 字符串）不炸"""
    from clowder_analytics.web.app import _step_detail
    entry = {"step": "model.bar", "ok": True, "report": {"chart_spec": "bar"}}
    detail = _step_detail(entry)
    assert "bar" in detail
