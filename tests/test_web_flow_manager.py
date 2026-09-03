"""F002 G16: Web Flow Library 管理界面测试（查看/更新/删除）

测试策略（与 test_web_app.py 一致）：
- 页面函数可导入可调用
- steps 编辑解析（YAML 文本 → Step 列表）纯逻辑可测
- 元字段保护：编辑更新不改 stability / promoted_from_plan_id（除非用户显式改）
- 删除二次确认的状态机逻辑可测

完整 UI 交互（按钮点击流）靠人工跑 streamlit 验收。
"""
from __future__ import annotations

import pytest

from clowder_analytics.flow_library.models import Template
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.plan import Step


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


# ===== 页面函数可导入 =====

def test_flow_manager_importable():
    from clowder_analytics.web.app import _render_flow_library_manager
    assert callable(_render_flow_library_manager)


# ===== steps YAML 编辑解析 =====

def test_parse_steps_yaml_valid():
    """合法 YAML steps 文本 → Step 列表"""
    from clowder_analytics.web.app import _parse_steps_yaml

    text = """
- op: model.topn
  args:
    group_by: [brand]
    value_col: sales
    n: 30
- op: clean.remove_duplicates
  args:
    keys: [spu_id]
"""
    steps = _parse_steps_yaml(text)
    assert len(steps) == 2
    assert steps[0].op == "model.topn"
    assert steps[0].args["n"] == 30
    assert steps[1].op == "clean.remove_duplicates"


def test_parse_steps_yaml_invalid_raises():
    """非法 YAML → 抛 ValueError 带"steps"提示（页面捕获显示给用户）"""
    from clowder_analytics.web.app import _parse_steps_yaml

    with pytest.raises(ValueError):
        _parse_steps_yaml("{{not yaml")


def test_parse_steps_yaml_non_list_raises():
    """合法 YAML 但不是列表 → ValueError"""
    from clowder_analytics.web.app import _parse_steps_yaml

    with pytest.raises(ValueError):
        _parse_steps_yaml("op: model.topn")


def test_parse_steps_yaml_missing_op_raises():
    """列表项缺 op 字段 → ValueError"""
    from clowder_analytics.web.app import _parse_steps_yaml

    with pytest.raises(ValueError):
        _parse_steps_yaml("- args: {}")


# ===== 元字段保护（G16 验收点）=====

def test_apply_template_edit_keeps_meta_fields(tmp_path):
    """编辑保存：steps/intent 变更，promoted_from_plan_id / stability 保持原值"""
    from clowder_analytics.web.app import _apply_template_edit

    lib = FlowLibrary(base_dir=tmp_path)
    lib.save_template(_tpl())

    edited = _apply_template_edit(
        lib,
        template_id="tpl-a",
        steps=[Step(op="model.aggregate", args={"group_by": ["brand"], "agg": {"sales": "sum"}})],
        intent="趋势分析",
        reviewer_enabled=False,
    )

    assert edited.steps[0].op == "model.aggregate"
    assert edited.intent == "趋势分析"
    assert edited.reviewer_enabled is False
    # 元字段不丢（G16 验收点）
    assert edited.promoted_from_plan_id == "plan-orig"
    assert edited.stability == "stable"
    # 已持久化
    loaded = lib.load_template("tpl-a")
    assert loaded.promoted_from_plan_id == "plan-orig"
    assert loaded.stability == "stable"


def test_apply_template_edit_unknown_id_raises(tmp_path):
    from clowder_analytics.web.app import _apply_template_edit

    lib = FlowLibrary(base_dir=tmp_path)
    with pytest.raises(KeyError):
        _apply_template_edit(
            lib, template_id="tpl-not-exist",
            steps=[], intent="x", reviewer_enabled=False,
        )
