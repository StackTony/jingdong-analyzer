"""F002 P4: 晋升 + 降级机制（spec §7.3 / §7.4）

晋升（§7.3 路径1）：
- Plan 在 (fp, intent) 下被命中执行 ≥ N=3 次
- 且成功率 ≥ 80%
- 且无人工修正（user_adopted != False 且 user_correction is None）
- → 自动晋升为 A 轨 Template，stability=candidate

降级（§7.4）：
- A 轨 Template 连续 K=5 次失败 → stability=deprecated
- 不再参与匹配（match_template 已跳过 deprecated）

设计依据：spec §7.3 / §7.4 / AC-5
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from clowder_analytics.flow_library.models import RunRecord, Template
from clowder_analytics.flow_library.store import FlowLibrary


# spec §7.3 路径1 阈值
PROMOTE_MIN_RUNS = 3
PROMOTE_MIN_SUCCESS_RATE = 0.80

# spec §7.4 降级阈值
DEMOTE_CONSECUTIVE_FAILURES = 5


class Promoter:
    """晋升 + 降级执行器

    用法：
        p = Promoter(library=lib)
        if p.check_promote(fp, intent, plan_id):
            tpl_id = p.promote(fp, intent, plan_id)
        p.check_and_demote(template_id)
        promoted_ids = p.scan_and_promote()
    """

    def __init__(self, library: FlowLibrary):
        self.library = library

    # ===== 晋升检查 =====

    def check_promote(self, fp: str, intent: str, plan_id: str) -> bool:
        """检查某 Plan 是否满足晋升条件（spec §7.3 路径1）

        条件：
        1. (fp, intent, plan_id) 下执行次数 ≥ N=3
        2. 成功率 ≥ 80%
        3. 无人工修正：所有 run 的 user_adopted != False 且 user_correction is None
        """
        runs = [
            r for r in self.library.list_runs()
            if r.schema_fingerprint == fp
            and r.intent == intent
            and r.matched_plan_id == plan_id
        ]
        if len(runs) < PROMOTE_MIN_RUNS:
            return False
        # 成功率
        ok_count = sum(1 for r in runs if r.success)
        success_rate = ok_count / len(runs)
        if success_rate < PROMOTE_MIN_SUCCESS_RATE:
            return False
        # 人工修正检查
        for r in runs:
            if r.user_adopted is False:
                return False
            if r.user_correction is not None:
                return False
        return True

    # ===== 晋升动作 =====

    def promote(self, fp: str, intent: str, plan_id: str) -> str | None:
        """满足条件则晋升 Plan 为 A 轨 Template（candidate）

        Returns:
            template_id；条件不满足返回 None
        """
        if not self.check_promote(fp, intent, plan_id):
            return None

        # 幂等：已有同 promoted_from_plan_id 的 candidate 不重复
        for t in self.library.list_templates():
            if t.promoted_from_plan_id == plan_id and t.stability != "deprecated":
                return t.template_id

        plan = self.library.load_plan(plan_id)
        if plan is None:
            return None

        tpl_id = f"tpl-{plan_id}-{intent[:8]}".replace(" ", "_")
        tpl = Template(
            template_id=tpl_id,
            intent=intent,
            schema_fingerprint=fp,
            steps=plan.steps,
            reviewer_enabled=plan.reviewer_enabled,
            fallback_strategy=plan.fallback_strategy,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            promoted_from_plan_id=plan_id,
            stability="candidate",
            confidence=0.0,  # candidate 初始 0；命中后提升
        )
        self.library.save_template(tpl)
        return tpl_id

    # ===== 降级 =====

    def check_and_demote(self, template_id: str) -> bool:
        """检查并执行降级（spec §7.4）

        连续 K=5 次失败 → deprecated
        中间有成功则计数重置

        Returns:
            是否执行了降级
        """
        tpl = self.library.load_template(template_id)
        if tpl is None:
            return False
        if tpl.stability == "deprecated":
            return False

        # 取该 template 的运行记录，按时间升序
        runs = sorted(
            (r for r in self.library.list_runs()
             if r.matched_template_id == template_id),
            key=lambda r: r.timestamp,
        )
        # 找连续 K 次失败
        consecutive_failures = 0
        for r in runs:
            if not r.success:
                consecutive_failures += 1
                if consecutive_failures >= DEMOTE_CONSECUTIVE_FAILURES:
                    tpl.stability = "deprecated"
                    self.library.save_template(tpl)
                    return True
            else:
                consecutive_failures = 0  # 重置
        return False

    # ===== 批量扫描 =====

    def scan_and_promote(self) -> list[str]:
        """扫描所有 (fp, intent, plan_id) 组合，晋升满足条件的 Plan

        用于定期触发（如 CLI `jd-analyze flow scan-promote`）。
        """
        # 收集所有 (fp, intent, plan_id) 组合
        # spec §7.3 路径1"命中执行 ≥ N 次"不区分路由——A/B/fallback 都算命中
        # 关羽 P2-2 修复：原过滤 r.route == "B" 漏 fallback 路径
        combos: set[tuple[str, str, str]] = set()
        for r in self.library.list_runs():
            if r.matched_plan_id:
                combos.add((r.schema_fingerprint, r.intent, r.matched_plan_id))

        promoted_ids: list[str] = []
        for fp, intent, plan_id in combos:
            tpl_id = self.promote(fp, intent, plan_id)
            if tpl_id:
                # 新晋升的（不是幂等返回的旧模板）才加入
                promoted_ids.append(tpl_id)
        return promoted_ids
