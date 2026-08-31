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
    """冷启动模板转 Plan 后能被 executor 跑通"""
    from clowder_analytics.orchestrator.executor import execute
    from clowder_analytics.orchestrator.plan import Plan

    lib = FlowLibrary()
    cold_start = [t for t in lib.list_templates() if t.template_id.startswith("cold_start_")][0]

    # 构造一个能跑通的数据集
    df = pd.DataFrame({
        "brand": ["小米", "华为", "OPPO", "vivo"],
        "sales": [100, 200, 250, 180],
    })
    ds = Dataset(df=df, schema_fingerprint=compute_fingerprint(df))

    plan = Plan.from_dict(cold_start.to_plan_dict())
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
        assert result.llm_calls == 0


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
        assert stats.avg_llm_calls == 0.0


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
