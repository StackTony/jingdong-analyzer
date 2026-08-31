"""F002 P2: Flow Library + Router + 意图分类红测（spec §6 / §7）

P2 阶段实现：
- FlowLibrary: Template/Plan/RunRecord 的文件 CRUD（YAML/JSON/JSONL）
- IntentClassifier: 规则 + 关键词分类
- Router: A → B → fallback 三层匹配
- matcher: 精确指纹 + 意图匹配（P2 不做相似度，留 P4）
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.flow_library.models import RunRecord, Template
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.intent_classifier import classify_intent
from clowder_analytics.orchestrator.plan import Plan, Step
from clowder_analytics.orchestrator.router import Route, route


# ===== IntentClassifier =====

def test_classify_intent_topn():
    assert classify_intent("找出销售额 Top30 品牌趋势") == "TopN 趋势分析"
    assert classify_intent("top10 品牌是哪些") == "TopN 趋势分析"


def test_classify_intent_anomaly():
    assert classify_intent("哪些品牌销量异常") == "异常归因"
    assert classify_intent("找异常值") == "异常归因"


def test_classify_intent_trend():
    assert classify_intent("过去 6 个月趋势") == "趋势分析"
    assert classify_intent("月度走势") == "趋势分析"


def test_classify_intent_correlation():
    assert classify_intent("价格和销量相关性") == "相关性分析"


def test_classify_intent_compare():
    assert classify_intent("品类对比") == "品类对比"


def test_classify_intent_unknown_returns_none():
    """未命中关键词返回 None 或 'unknown'"""
    result = classify_intent("一段无关键词的文字")
    assert result is None or result == "unknown"


# ===== FlowLibrary CRUD =====

@pytest.fixture
def empty_library(tmp_path):
    return FlowLibrary(base_dir=tmp_path)


def test_library_creates_dirs(empty_library, tmp_path):
    """初始化时建好 templates/plans/runs 三个子目录"""
    assert (tmp_path / "templates").is_dir()
    assert (tmp_path / "plans").is_dir()
    assert (tmp_path / "runs").is_dir()


def test_library_save_and_load_template(empty_library):
    tpl = Template(
        template_id="topn_brand_sales",
        intent="TopN 趋势分析",
        schema_fingerprint="abc123",
        steps=[Step(op="model.topn", args={"n": 30})],
        stability="stable",
    )
    empty_library.save_template(tpl)
    loaded = empty_library.load_template("topn_brand_sales")
    assert loaded is not None
    assert loaded.template_id == "topn_brand_sales"
    assert loaded.intent == "TopN 趋势分析"
    assert loaded.steps[0].op == "model.topn"
    assert loaded.stability == "stable"


def test_library_list_templates(empty_library):
    empty_library.save_template(Template(
        template_id="t1", intent="A", schema_fingerprint="f1", steps=[]
    ))
    empty_library.save_template(Template(
        template_id="t2", intent="B", schema_fingerprint="f2", steps=[]
    ))
    ids = [t.template_id for t in empty_library.list_templates()]
    assert set(ids) == {"t1", "t2"}


def test_library_save_and_load_plan(empty_library):
    plan = Plan(
        plan_id="plan-001",
        intent="TopN 趋势分析",
        steps=[Step(op="model.topn", args={"n": 10})],
    )
    empty_library.save_plan(plan)
    loaded = empty_library.load_plan("plan-001")
    assert loaded is not None
    assert loaded.plan_id == "plan-001"
    assert loaded.steps[0].args["n"] == 10


def test_library_list_plans(empty_library):
    empty_library.save_plan(Plan(plan_id="p1", intent="A", steps=[]))
    empty_library.save_plan(Plan(plan_id="p2", intent="B", steps=[]))
    ids = [p.plan_id for p in empty_library.list_plans()]
    assert set(ids) == {"p1", "p2"}


def test_library_save_run_record_appends_jsonl(empty_library):
    """RunRecord 写入 runs/*.jsonl，追加模式"""
    rec = RunRecord(
        schema_fingerprint="fp",
        intent="TopN 趋势分析",
        route="A",
        success=True,
        matched_template_id="t1",
    )
    empty_library.save_run(rec)
    empty_library.save_run(RunRecord(
        schema_fingerprint="fp2", intent="异常归因", route="B", success=False,
    ))
    runs = empty_library.list_runs()
    assert len(runs) == 2
    assert runs[0].route == "A"
    assert runs[1].route == "B"


def test_library_template_persisted_as_yaml(empty_library, tmp_path):
    """Template 按 spec §7.2 存为 YAML"""
    tpl = Template(
        template_id="t_yaml", intent="测试", schema_fingerprint="fp",
        steps=[Step(op="model.topn", args={"n": 5})],
    )
    empty_library.save_template(tpl)
    yaml_path = tmp_path / "templates" / "t_yaml.yaml"
    assert yaml_path.exists()
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["template_id"] == "t_yaml"
    assert data["steps"][0]["op"] == "model.topn"


def test_library_plan_persisted_as_json(empty_library, tmp_path):
    """Plan 按 spec §5.1 存为 JSON"""
    plan = Plan(plan_id="p_json", intent="测试", steps=[Step(op="clean.remove_duplicates")])
    empty_library.save_plan(plan)
    json_path = tmp_path / "plans" / "p_json.json"
    assert json_path.exists()
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["plan_id"] == "p_json"


# ===== Matcher =====

def test_match_template_exact_fingerprint_and_intent(empty_library):
    """A 轨匹配：精确 fp + intent + stability=stable"""
    tpl = Template(
        template_id="topn_stable", intent="TopN 趋势分析",
        schema_fingerprint="fp_exact", steps=[],
        stability="stable", confidence=0.9,
    )
    empty_library.save_template(tpl)
    matched = empty_library.match_template("fp_exact", "TopN 趋势分析")
    assert matched is not None
    assert matched.template_id == "topn_stable"


def test_match_template_intent_mismatch_returns_none(empty_library):
    empty_library.save_template(Template(
        template_id="t", intent="TopN 趋势分析",
        schema_fingerprint="fp", steps=[], stability="stable",
    ))
    assert empty_library.match_template("fp", "异常归因") is None


def test_match_template_candidate_skipped_when_stable_exists(empty_library):
    """同 fp+intent 有 stable 和 candidate 时优先 stable"""
    empty_library.save_template(Template(
        template_id="t_stable", intent="X", schema_fingerprint="fp",
        steps=[], stability="stable",
    ))
    empty_library.save_template(Template(
        template_id="t_candidate", intent="X", schema_fingerprint="fp",
        steps=[], stability="candidate",
    ))
    matched = empty_library.match_template("fp", "X")
    assert matched.template_id == "t_stable"


def test_match_template_candidate_fallback_when_no_stable(empty_library):
    """无 stable 时 candidate 兜底"""
    empty_library.save_template(Template(
        template_id="t_cand", intent="X", schema_fingerprint="fp",
        steps=[], stability="candidate",
    ))
    matched = empty_library.match_template("fp", "X")
    assert matched.template_id == "t_cand"


def test_match_template_deprecated_never_matched(empty_library):
    """deprecated 不参与匹配（spec §7.4）"""
    empty_library.save_template(Template(
        template_id="t_dep", intent="X", schema_fingerprint="fp",
        steps=[], stability="deprecated",
    ))
    assert empty_library.match_template("fp", "X") is None


def test_match_plan_exact(empty_library):
    """B 轨匹配：精确 fp + intent"""
    empty_library.save_plan(Plan(
        plan_id="p1", intent="TopN 趋势分析",
        schema_fingerprint="fp_x", steps=[],
    ))
    matched = empty_library.match_plan("fp_x", "TopN 趋势分析")
    assert matched is not None
    assert matched.plan_id == "p1"


# ===== Router =====

def _make_dataset(df: pd.DataFrame) -> Dataset:
    return Dataset(df=df, schema_fingerprint=compute_fingerprint(df))


def test_router_matches_a_track(empty_library):
    """A 轨命中：fp+intent 精确匹配 stable template"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    empty_library.save_template(Template(
        template_id="t", intent="TopN 趋势分析",
        schema_fingerprint=ds.schema_fingerprint, steps=[],
        stability="stable", confidence=0.9,
    ))
    r = route("Top30 品牌趋势", ds, library=empty_library)
    assert r.kind == "A"
    assert r.template is not None
    assert r.template.template_id == "t"
    assert r.generate is False


def test_router_falls_back_to_b(empty_library):
    """A 轨无命中时落 B 轨"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    empty_library.save_plan(Plan(
        plan_id="p", intent="TopN 趋势分析",
        schema_fingerprint=ds.schema_fingerprint, steps=[],
    ))
    r = route("Top30 品牌", ds, library=empty_library)
    assert r.kind == "B"
    assert r.plan is not None
    assert r.plan.plan_id == "p"
    assert r.generate is False


def test_router_falls_back_to_fallback_when_no_match(empty_library):
    """A/B 都无命中 → fallback（P2 阶段标记 generate=True，但 LLM 留 P3）"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    r = route("Top30 品牌", ds, library=empty_library)
    assert r.kind == "fallback"
    assert r.generate is True
    assert r.template is None
    assert r.plan is None


def test_router_uses_intent_from_classifier(empty_library):
    """Router 内部调 classify_intent，关键词 → intent → 匹配"""
    df = pd.DataFrame({"brand": ["a"], "sales": [10]})
    ds = _make_dataset(df)
    empty_library.save_template(Template(
        template_id="t", intent="TopN 趋势分析",
        schema_fingerprint=ds.schema_fingerprint, steps=[],
        stability="stable", confidence=0.9,
    ))
    # 用户问句含 "Top30" → intent="TopN 趋势分析"
    r = route("找 Top30 品牌", ds, library=empty_library)
    assert r.kind == "A"


def test_route_dataclass_fields():
    """Route dataclass 含 kind/template/plan/generate/intent 字段"""
    r = Route(kind="A", intent="X")
    assert r.kind == "A"
    assert r.template is None
    assert r.plan is None
    assert r.generate is False
    assert r.intent == "X"
