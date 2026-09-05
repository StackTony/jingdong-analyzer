"""F002 P6: 冷启动模板 + 命中率仪表盘红测（spec AC-10 / AC-12）

AC-10: Flow Library 自带 ≥ 3 个 A 轨模板冷启动样本
- TopN 趋势分析
- 异常归因
- 品类对比

通配模板：schema_fingerprint="*" 或 "_any_" 的模板作为 intent 级稳定兜底
（冷启动期用户数据 schema 不固定，用通配匹配）

AC-12: 仪表盘可观测 A 命中率 / B 命中率 / 兜底率 / 平均 LLM 调用数
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.models import Template
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.run import run
from clowder_analytics.flow_library.dashboard import (
    compute_stats,
    format_stats,
)


# ===== 冷启动模板通配匹配 =====

def test_wildcard_template_matches_any_fingerprint():
    """schema_fingerprint='*' 的模板匹配任意指纹 + 同 intent"""
    lib = FlowLibrary(base_dir=__import__("tempfile").mkdtemp())
    lib.save_template(Template(
        template_id="topn_cold_start",
        intent="TopN 趋势分析",
        schema_fingerprint="*",  # 通配
        steps=[],
        stability="stable", confidence=0.6,
    ))
    matched = lib.match_template("any_fp_xyz", "TopN 趋势分析")
    assert matched is not None
    assert matched.template_id == "topn_cold_start"


def test_exact_template_beats_wildcard():
    """精确匹配优先于通配"""
    lib = FlowLibrary(base_dir=__import__("tempfile").mkdtemp())
    lib.save_template(Template(
        template_id="exact_tpl", intent="X",
        schema_fingerprint="fp_exact", steps=[],
        stability="stable", confidence=0.9,
    ))
    lib.save_template(Template(
        template_id="wildcard_tpl", intent="X",
        schema_fingerprint="*", steps=[],
        stability="stable", confidence=0.6,
    ))
    matched = lib.match_template("fp_exact", "X")
    assert matched.template_id == "exact_tpl"


def test_three_cold_start_templates_loaded():
    """Flow Library 默认加载 3 个冷启动模板（spec AC-10）"""
    lib = FlowLibrary()  # 默认库（包内 flow_library_data/）
    templates = lib.list_templates()
    template_ids = [t.template_id for t in templates]
    # 至少含 3 个冷启动模板
    cold_start = [t for t in templates if t.template_id.startswith("cold_start_")]
    assert len(cold_start) >= 3

    intents = {t.intent for t in cold_start}
    assert "TopN 趋势分析" in intents
    assert "异常归因" in intents
    assert "品类对比" in intents


def test_cold_start_templates_are_stable():
    """冷启动模板默认 stability=stable"""
    lib = FlowLibrary()
    cold_start = [t for t in lib.list_templates() if t.template_id.startswith("cold_start_")]
    assert all(t.stability == "stable" for t in cold_start)


def test_cold_start_templates_have_steps():
    """每个冷启动模板有具体 steps"""
    lib = FlowLibrary()
    cold_start = [t for t in lib.list_templates() if t.template_id.startswith("cold_start_")]
    for t in cold_start:
        assert len(t.steps) > 0
        assert all(s.op.startswith(("clean.", "model.")) for s in t.steps)


def test_cold_start_template_can_be_executed():
    """冷启动模板变量解析后转 Plan 能被 executor 跑通

    P1 修复后模板用 {{numeric_col}} / {{group_col}} 占位符，
    必须经 resolve_template_variables 注入列名才能执行。
    """
    from clowder_analytics.orchestrator.executor import execute
    from clowder_analytics.orchestrator.plan import Plan
    from clowder_analytics.orchestrator.run import resolve_template_variables

    lib = FlowLibrary()
    cold_start = [t for t in lib.list_templates() if t.template_id.startswith("cold_start_")][0]

    # 构造一个能跑通的数据集
    df = pd.DataFrame({
        "brand": ["小米", "华为", "OPPO", "vivo"],
        "sales": [100, 200, 250, 180],
    })
    ds = Dataset(df=df, schema_fingerprint=compute_fingerprint(df))

    # P1：变量解析后转 Plan
    resolved = resolve_template_variables(cold_start, ds)
    plan = Plan.from_dict(resolved.to_plan_dict())
    result = execute(plan, ds)
    assert all(s["ok"] for s in result.log)


# ===== run() 用冷启动模板 =====

def test_run_uses_cold_start_template_on_first_call():
    """首次运行（库空）命中冷启动 stable 模板走 A 轨（不调 LLM）"""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        lib = FlowLibrary(base_dir=td)
        # 临时把包内冷启动模板复制到临时库
        from clowder_analytics.flow_library.models import Template
        pkg_lib = FlowLibrary()
        for t in pkg_lib.list_templates():
            if t.template_id.startswith("cold_start_"):
                lib.save_template(t)

        df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
        ds = Dataset(df=df, schema_fingerprint=compute_fingerprint(df))

        result = run("Top30 品牌", ds, library=lib,
                     generator=FakePlanGenerator(), reviewer=FakeReviewer())
        assert result.route == "A"  # 命中冷启动模板
        # G18 语义：reviewer 被调也计 1 次（冷启动模板 reviewer_enabled=True）
        assert result.llm_calls == 1


# ===== 仪表盘 =====

def test_compute_stats_empty_library():
    """空库统计全 0"""
    import tempfile
    lib = FlowLibrary(base_dir=tempfile.mkdtemp())
    stats = compute_stats(lib)
    assert stats.total_runs == 0
    assert stats.a_hits == 0
    assert stats.b_hits == 0
    assert stats.fallback_hits == 0
    assert stats.success_rate == 0.0
    assert stats.avg_llm_calls == 0.0


def test_compute_stats_after_runs():
    """跑过几次后统计正确"""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        lib = FlowLibrary(base_dir=td)
        # 复制冷启动模板
        pkg_lib = FlowLibrary()
        for t in pkg_lib.list_templates():
            if t.template_id.startswith("cold_start_"):
                lib.save_template(t)

        df = pd.DataFrame({"brand": ["a", "b", "c"], "sales": [10, 20, 30]})
        ds = Dataset(df=df, schema_fingerprint=compute_fingerprint(df))

        # 跑 3 次
        for _ in range(3):
            run("Top30", ds, library=lib,
                generator=FakePlanGenerator(), reviewer=FakeReviewer())

        stats = compute_stats(lib)
        assert stats.total_runs == 3
        assert stats.a_hits == 3  # 全部命中冷启动模板
        assert stats.fallback_hits == 0
        # G18 语义：reviewer 调用计入 llm_calls（每次 run 调 reviewer 1 次）
    assert stats.avg_llm_calls == 1.0


def test_format_stats_output():
    """format_stats 输出含关键字段"""
    import tempfile
    lib = FlowLibrary(base_dir=tempfile.mkdtemp())
    stats = compute_stats(lib)
    output = format_stats(stats)
    assert "A 轨" in output or "A hits" in output
    assert "B 轨" in output or "B hits" in output
    assert "兜底" in output or "fallback" in output.lower()
    assert "LLM" in output


# ===== P1: 模板列名变量化 + required_columns 校验 =====
# 外部 AI P1 finding：模板硬编码 sales/brand 列，schema_fingerprint='*'
# 通配任意数据源，命中后列名不匹配必失败。
# P3 finding：cold_start_category_compare.yaml group_by=[brand] 与
# intent "品类对比" 不符。
#
# 修法：
# - 模板 args 支持 {{numeric_col}} / {{group_col}} / {{time_col}} 占位符
# - run() 命中模板后，用 dataset 自动匹配列名注入变量
# - 模板加 required_columns 字段校验（可选）

def test_cold_start_template_variables_resolved_by_dataset():
    """模板 args 里的 {{numeric_col}} / {{group_col}} 应被 dataset 实际列名替换

    外部 AI P1 修复：模板硬编码 sales 列，遇到 sales_value_proxy 等列名
    必失败。修法：模板用占位符，run() 注入。
    """
    from clowder_analytics.orchestrator.run import resolve_template_variables
    from clowder_analytics.flow_library.models import Template
    from clowder_analytics.orchestrator.plan import Step

    # 构造一个用占位符的模板
    tpl = Template(
        template_id="test_var_tpl",
        intent="TopN 趋势分析",
        schema_fingerprint="*",
        steps=[
            Step(op="model.aggregate", args={
                "group_by": ["{{group_col}}"],
                "agg": {"{{numeric_col}}": "sum"},
            }),
        ],
        stability="stable", confidence=0.6,
    )

    # 数据集列名不是 sales/brand
    df = pd.DataFrame({
        "产品名": ["a", "b", "c"],
        "销售额": [100, 200, 50],
    })
    ds = Dataset(df=df, schema_fingerprint=compute_fingerprint(df))

    resolved = resolve_template_variables(tpl, ds)
    # group_col 应被解析为"产品名"（第一个非数值列）
    assert resolved.steps[0].args["group_by"] == ["产品名"]
    # numeric_col 应被解析为"销售额"
    assert "{{numeric_col}}" not in str(resolved.steps[0].args["agg"])
    assert "销售额" in str(resolved.steps[0].args["agg"])


def test_cold_start_category_compare_uses_category_not_brand():
    """P3：品类对比模板 group_by 应是 category 类列，不是 brand

    外部 AI P3 finding：cold_start_category_compare.yaml group_by=[brand]
    与 intent "品类对比" 不符。
    """
    lib = FlowLibrary()
    cat_tpl = next(
        t for t in lib.list_templates()
        if t.template_id == "cold_start_category_compare"
    )
    # 检查模板的 group_by 引用的是占位符或 category 类列，不是硬编码 brand
    group_by_str = str(cat_tpl.steps)
    # 不能硬编码 brand
    assert "brand" not in group_by_str.lower() or "{{" in group_by_str, (
        f"cold_start_category_compare 不应硬编码 brand 列，"
        f"实际 steps: {cat_tpl.steps}"
    )


def test_run_resolves_template_variables_before_execute():
    """run() 命中模板后应在执行前注入 dataset 的列名

    验证：数据集列名是"产品"/"销售额"（不是 sales/brand），
    命中模板后能跑通（不因列名不匹配失败）。
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        lib = FlowLibrary(base_dir=td)
        pkg_lib = FlowLibrary()
        for t in pkg_lib.list_templates():
            if t.template_id.startswith("cold_start_"):
                lib.save_template(t)

        # 列名故意避开 sales/brand
        df = pd.DataFrame({
            "产品": ["小米", "华为", "OPPO"],
            "金额": [100, 200, 150],
        })
        ds = Dataset(df=df, schema_fingerprint=compute_fingerprint(df))

        result = run("Top30", ds, library=lib,
                     generator=FakePlanGenerator(), reviewer=FakeReviewer())
        assert result.route == "A"
        # 命中模板后所有 step 应成功（变量已注入）
        assert all(s["ok"] for s in result.log), (
            f"冷启动模板命中后 step 失败：{[s for s in result.log if not s['ok']]}"
        )
