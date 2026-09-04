"""F002 P4: 晋升 + 降级机制红测（spec §7.3 / §7.4）

晋升（§7.3 路径1）：
- Plan 在 (fp, intent) 下执行 ≥ N=3 次
- 且成功率 ≥ 80%
- 且无人工修正（user_adopted != False 且 user_correction is None）
- → 自动晋升为 A 轨 Template，stability=candidate

降级（§7.4）：
- A 轨 Template 连续 K=5 次失败 → stability=deprecated
- 不再参与匹配

测试用 FlowLibrary(tmp_path) 隔离，不污染主库。
"""
from __future__ import annotations

import pandas as pd
import pytest

from clowder_analytics.adapters.base import Dataset, compute_fingerprint
from clowder_analytics.flow_library.models import RunRecord, Template
from clowder_analytics.flow_library.promoter import Promoter
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.plan import Plan, Step


@pytest.fixture
def library(tmp_path):
    return FlowLibrary(base_dir=tmp_path)


@pytest.fixture
def promoter(library):
    return Promoter(library=library)


def _run_record(fp: str, intent: str, success: bool, plan_id: str = "p1",
                user_adopted: bool | None = None, user_correction: str | None = None) -> RunRecord:
    return RunRecord(
        schema_fingerprint=fp, intent=intent, route="B", success=success,
        matched_plan_id=plan_id, user_adopted=user_adopted, user_correction=user_correction,
    )


# ===== 晋升条件检查 =====

def test_promote_check_no_runs_returns_false(promoter, library):
    """无运行记录时不晋升"""
    assert promoter.check_promote("fp", "TopN 趋势分析", "plan-1") is False


def test_promote_check_under_n_returns_false(promoter, library):
    """运行 < N 次不晋升"""
    for _ in range(2):
        library.save_run(_run_record("fp", "TopN 趋势分析", success=True, plan_id="plan-1"))
    assert promoter.check_promote("fp", "TopN 趋势分析", "plan-1") is False


def test_promote_check_n_runs_high_success_no_correction(promoter, library):
    """N=3 次成功 + 无修正 → 可晋升"""
    for _ in range(3):
        library.save_run(_run_record("fp", "TopN 趋势分析", success=True, plan_id="plan-1"))
    assert promoter.check_promote("fp", "TopN 趋势分析", "plan-1") is True


def test_promote_check_low_success_rate_returns_false(promoter, library):
    """成功率 < 80% 不晋升（3 次 1 失败 = 66.7%）"""
    library.save_run(_run_record("fp", "X", success=True, plan_id="p1"))
    library.save_run(_run_record("fp", "X", success=True, plan_id="p1"))
    library.save_run(_run_record("fp", "X", success=False, plan_id="p1"))
    assert promoter.check_promote("fp", "X", "p1") is False


def test_promote_check_with_user_correction_returns_false(promoter, library):
    """有人工修正不晋升（用户改了 args）"""
    for _ in range(2):
        library.save_run(_run_record("fp", "X", success=True, plan_id="p1"))
    library.save_run(_run_record(
        "fp", "X", success=True, plan_id="p1",
        user_correction="改了 n=50",
    ))
    assert promoter.check_promote("fp", "X", "p1") is False


def test_promote_check_with_user_rejected_returns_false(promoter, library):
    """用户拒绝过的 Plan 不晋升"""
    for _ in range(2):
        library.save_run(_run_record("fp", "X", success=True, plan_id="p1"))
    library.save_run(_run_record(
        "fp", "X", success=True, plan_id="p1", user_adopted=False,
    ))
    assert promoter.check_promote("fp", "X", "p1") is False


def test_promote_check_only_counts_matching_plan_id(promoter, library):
    """只算同 plan_id 的运行记录"""
    # 3 次但 plan_id 不同
    library.save_run(_run_record("fp", "X", success=True, plan_id="p1"))
    library.save_run(_run_record("fp", "X", success=True, plan_id="p2"))
    library.save_run(_run_record("fp", "X", success=True, plan_id="p2"))
    # p1 只有 1 次，不够 N
    assert promoter.check_promote("fp", "X", "p1") is False
    # p2 有 2 次，也不够
    assert promoter.check_promote("fp", "X", "p2") is False


# ===== 晋升动作 =====

def test_promote_creates_candidate_template(promoter, library):
    """晋升时创建 stability=candidate 的 Template"""
    # 先存 Plan
    plan = Plan(
        plan_id="plan-x", intent="TopN 趋势分析", schema_fingerprint="fp",
        steps=[Step(op="model.topn", args={"n": 30})],
    )
    library.save_plan(plan)
    # 3 次成功
    for _ in range(3):
        library.save_run(_run_record("fp", "TopN 趋势分析", success=True, plan_id="plan-x"))

    tpl_id = promoter.promote("fp", "TopN 趋势分析", "plan-x")
    assert tpl_id is not None
    tpl = library.load_template(tpl_id)
    assert tpl is not None
    assert tpl.stability == "candidate"
    assert tpl.promoted_from_plan_id == "plan-x"
    assert tpl.intent == "TopN 趋势分析"
    assert tpl.schema_fingerprint == "fp"
    assert len(tpl.steps) == 1
    assert tpl.steps[0].op == "model.topn"


def test_promote_returns_none_when_conditions_not_met(promoter, library):
    """条件不满足时返回 None"""
    library.save_run(_run_record("fp", "X", success=True, plan_id="p1"))
    result = promoter.promote("fp", "X", "p1")
    assert result is None


def test_promote_idempotent_does_not_duplicate(promoter, library):
    """同 plan 已晋升过，再晋升不重复创建"""
    plan = Plan(
        plan_id="plan-y", intent="X", schema_fingerprint="fp",
        steps=[Step(op="model.topn")],
    )
    library.save_plan(plan)
    for _ in range(3):
        library.save_run(_run_record("fp", "X", success=True, plan_id="plan-y"))

    first_id = promoter.promote("fp", "X", "plan-y")
    second_id = promoter.promote("fp", "X", "plan-y")
    # 已有 candidate 时不重复创建
    assert first_id is not None
    # second 应该返回已有的或 None，但不能新建
    if second_id is not None:
        assert second_id == first_id
    templates = [t for t in library.list_templates() if t.promoted_from_plan_id == "plan-y"]
    assert len(templates) == 1


# ===== 降级机制 =====

def test_demote_after_k_consecutive_failures(promoter, library):
    """连续 K=5 次失败 → deprecated"""
    tpl = Template(
        template_id="t1", intent="X", schema_fingerprint="fp",
        steps=[], stability="stable",
    )
    library.save_template(tpl)
    # 5 次连续失败
    for _ in range(5):
        library.save_run(RunRecord(
            schema_fingerprint="fp", intent="X", route="A",
            success=False, matched_template_id="t1",
        ))
    demoted = promoter.check_and_demote("t1")
    assert demoted is True
    tpl_after = library.load_template("t1")
    assert tpl_after.stability == "deprecated"


def test_demote_resets_on_success(promoter, library):
    """中间成功一次则连续失败计数重置"""
    tpl = Template(
        template_id="t2", intent="X", schema_fingerprint="fp",
        steps=[], stability="stable",
    )
    library.save_template(tpl)
    # 4 失败 + 1 成功 + 4 失败 = 不够 K=5 连续
    for _ in range(4):
        library.save_run(RunRecord(
            schema_fingerprint="fp", intent="X", route="A",
            success=False, matched_template_id="t2",
        ))
    library.save_run(RunRecord(
        schema_fingerprint="fp", intent="X", route="A",
        success=True, matched_template_id="t2",
    ))
    for _ in range(4):
        library.save_run(RunRecord(
            schema_fingerprint="fp", intent="X", route="A",
            success=False, matched_template_id="t2",
        ))
    demoted = promoter.check_and_demote("t2")
    assert demoted is False
    tpl_after = library.load_template("t2")
    assert tpl_after.stability == "stable"


def test_demote_skips_already_deprecated(promoter, library):
    """已 deprecated 的不重复处理"""
    tpl = Template(
        template_id="t3", intent="X", schema_fingerprint="fp",
        steps=[], stability="deprecated",
    )
    library.save_template(tpl)
    result = promoter.check_and_demote("t3")
    assert result is False  # 无操作


# ===== 自进化闭环：检查所有 Plan 的晋升机会 =====

def test_scan_and_promote_finds_all_promotable(promoter, library):
    """扫描所有 (fp, intent, plan_id) 组合，晋升符合条件的"""
    # Plan A: 3 次成功，可晋升
    library.save_plan(Plan(plan_id="a", intent="X", schema_fingerprint="fp_a", steps=[]))
    for _ in range(3):
        library.save_run(_run_record("fp_a", "X", success=True, plan_id="a"))
    # Plan B: 2 次成功，不够
    library.save_plan(Plan(plan_id="b", intent="Y", schema_fingerprint="fp_b", steps=[]))
    for _ in range(2):
        library.save_run(_run_record("fp_b", "Y", success=True, plan_id="b"))

    promoted = promoter.scan_and_promote()
    assert len(promoted) == 1
    assert library.load_template(promoted[0]) is not None


# ===== P4: scan_and_promote 不应重复报告已晋升模板（幂等） =====

def test_scan_and_promote_idempotent_no_duplicates(promoter, library):
    """scan_and_promote 重复调用不应重复报告已晋升的模板

    外部 AI P4 finding：promote() 幂等命中旧模板返回 template_id，
    scan_and_promote 不区分"新晋升" vs "幂等命中"全 append，导致
    CLI `flow scan-promote` 重复打印已晋升模板。

    修法：scan_and_promote 只返回本次新晋升的（不包含幂等命中的）。
    """
    # Plan A: 3 次成功，可晋升
    library.save_plan(Plan(plan_id="a", intent="X", schema_fingerprint="fp_a", steps=[]))
    for _ in range(3):
        library.save_run(_run_record("fp_a", "X", success=True, plan_id="a"))

    # 第一次扫描：应晋升 1 个
    first = promoter.scan_and_promote()
    assert len(first) == 1

    # 第二次扫描：不应重复报告（无新增）
    second = promoter.scan_and_promote()
    assert len(second) == 0, (
        f"scan_and_promote 重复扫描应返回空列表（无新晋升），"
        f"实际返回 {second}（P4 幂等报告 bug）"
    )

    # 第三次：仍然 0（确认幂等稳定）
    third = promoter.scan_and_promote()
    assert len(third) == 0


# ===== G17 根因A 护栏：源 Plan 已删时不得从 run 记录复活晋升 =====
#
# 污染清理场景：删掉 fake plan 与 tpl 后，runs.jsonl 里残留的 ≥3 条成功
# run 记录仍会让 scan_and_promote 重新造出模板（错误图复活）。
# 契约：promote() 依赖 load_plan(plan_id)——源 Plan 不存在时返回 None，
# 不晋升。这条护栏保证「删 plan 即断根」，清理持久有效。


def test_scan_and_promote_skips_when_source_plan_deleted(promoter, library):
    """run 记录满足晋升条件，但源 Plan 已删 → 不复活晋升"""
    # 先建 plan + 3 次成功 run（满足晋升）
    library.save_plan(Plan(plan_id="ghost", intent="X", schema_fingerprint="fp_g", steps=[]))
    for _ in range(3):
        library.save_run(_run_record("fp_g", "X", success=True, plan_id="ghost"))

    # 断根：删除源 Plan（保留 run 记录，模拟污染清理现场）
    library.delete_plan("ghost")

    promoted = promoter.scan_and_promote()
    assert promoted == [], (
        f"源 Plan 已删时不应复活晋升，实际晋升 {promoted}——"
        f"清理会被残留 run 记录回滚"
    )
    # 且库里没有 ghost 来源的模板
    assert all(
        t.promoted_from_plan_id != "ghost" for t in library.list_templates()
    )


def test_promote_returns_none_when_plan_missing(promoter, library):
    """promote 直接调用：plan_id 无对应 Plan → None（不抛、不造空模板）"""
    for _ in range(3):
        library.save_run(_run_record("fp_h", "Y", success=True, plan_id="gone"))
    assert promoter.promote("fp_h", "Y", "gone") is None
    assert library.list_templates() == []

