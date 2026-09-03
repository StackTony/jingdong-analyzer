"""F002 G16: Flow Library 模板/Plan CRUD 红测（界面管理的 store 层支撑）

铲屎官 2026-09-03 需求："当前工具没法手动界面查看更新和删除已有的 Plan 模板"。

store 层补齐：
- delete_template / delete_plan（删除，破坏性操作，web 层负责二次确认）
- update_template / update_plan（更新，保留 promoted_from_plan_id / stability 元字段一致）
- 删除不存在的 id 抛 KeyError（明确报错优于静默）
"""
from __future__ import annotations

import pytest

from clowder_analytics.flow_library.models import Template
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.plan import Plan, Step


def _tpl(template_id: str = "tpl-a", stability: str = "stable") -> Template:
    return Template(
        template_id=template_id,
        intent="TopN 趋势分析",
        schema_fingerprint="fp1",
        steps=[Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 10})],
        reviewer_enabled=True,
        stability=stability,
        promoted_from_plan_id="plan-orig",
    )


def _plan(plan_id: str = "plan-1") -> Plan:
    return Plan(
        plan_id=plan_id,
        intent="TopN 趋势分析",
        schema_fingerprint="fp1",
        steps=[Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 10})],
    )


# ===== delete_template =====

def test_delete_template_removes_file(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_template(_tpl())
    assert lib.load_template("tpl-a") is not None

    deleted = lib.delete_template("tpl-a")

    assert deleted is True
    assert lib.load_template("tpl-a") is None


def test_delete_template_missing_raises_keyerror(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    with pytest.raises(KeyError):
        lib.delete_template("tpl-not-exist")


def test_delete_template_does_not_touch_others(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_template(_tpl("tpl-a"))
    lib.save_template(_tpl("tpl-b", stability="candidate"))

    lib.delete_template("tpl-a")

    assert lib.load_template("tpl-a") is None
    assert lib.load_template("tpl-b") is not None


# ===== update_template =====

def test_update_template_changes_steps_and_keeps_meta(tmp_path):
    """更新 steps / intent 等业务字段，promoted_from_plan_id / stability 不丢"""
    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_template(_tpl())

    updated = _tpl()
    updated.steps = [Step(op="model.topn", args={"group_by": ["brand"], "value_col": "sales", "n": 30})]
    updated.intent = "趋势分析"
    lib.update_template(updated)

    loaded = lib.load_template("tpl-a")
    assert loaded is not None
    assert loaded.steps[0].args["n"] == 30
    assert loaded.intent == "趋势分析"
    # 元字段一致（G16 验收点）
    assert loaded.promoted_from_plan_id == "plan-orig"
    assert loaded.stability == "stable"


def test_update_template_missing_raises_keyerror(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    with pytest.raises(KeyError):
        lib.update_template(_tpl("tpl-not-exist"))


def test_update_template_id_immutable(tmp_path):
    """update 传入了不存在的新 template_id → 报错而不是静默新建"""
    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_template(_tpl("tpl-a"))
    with pytest.raises(KeyError):
        lib.update_template(_tpl("tpl-other"))


# ===== delete_plan =====

def test_delete_plan_removes_file(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_plan(_plan())
    assert lib.load_plan("plan-1") is not None

    deleted = lib.delete_plan("plan-1")

    assert deleted is True
    assert lib.load_plan("plan-1") is None


def test_delete_plan_missing_raises_keyerror(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    with pytest.raises(KeyError):
        lib.delete_plan("plan-not-exist")


# ===== update_plan =====

def test_update_plan_changes_steps(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_plan(_plan())

    updated = _plan()
    updated.steps = [Step(op="model.aggregate", args={"group_by": ["brand"], "agg": {"sales": "sum"}})]
    lib.update_plan(updated)

    loaded = lib.load_plan("plan-1")
    assert loaded is not None
    assert loaded.steps[0].op == "model.aggregate"


def test_update_plan_missing_raises_keyerror(tmp_path):
    lib = FlowLibrary(base_dir=tmp_path)
    with pytest.raises(KeyError):
        lib.update_plan(_plan("plan-not-exist"))
