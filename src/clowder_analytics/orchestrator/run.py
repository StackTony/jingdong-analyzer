"""F002 P4: 端到端 run() 入口（spec §6.2 / §7.5）

把 P1.5 executor + P2 router + P3 generator/reviewer + P4 promoter 串成闭环：
1. route(question, dataset, library) → Route
2. 取 Plan：A 轨 from template.to_plan_dict(); B 轨 route.plan; fallback generator.generate()
3. execute(plan, dataset) → RunResult
4. reviewer_enabled 时调 reviewer.review()
5. save_run(RunRecord) 沉淀
6. fallback 生成的 Plan 也存 plans/ 供下次复用
7. scan_and_promote() 检查晋升机会

返回 RunResult（扩展含 matched_template_id / matched_plan_id / llm_calls）

设计依据：spec §6.2 / §7.1 / §7.5 / AC-6 / AC-11
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.ai.base import AIPlanGenerator, AIReviewer
from clowder_analytics.ai.fake import FakePlanGenerator, FakeReviewer
from clowder_analytics.flow_library.models import RunRecord
from clowder_analytics.flow_library.promoter import Promoter
from clowder_analytics.flow_library.store import FlowLibrary
from clowder_analytics.orchestrator.executor import execute
from clowder_analytics.orchestrator.plan import Plan, RunResult
from clowder_analytics.orchestrator.router import Route, route


@dataclass
class FullRunResult(RunResult):
    """run() 返回结果，扩展 RunResult 含路由与 LLM 元信息"""
    matched_template_id: str | None = None
    matched_plan_id: str | None = None
    llm_calls: int = 0
    duration_ms: int = 0

    def to_run_record(self, fp: str, intent: str) -> RunRecord:
        return RunRecord(
            schema_fingerprint=fp,
            intent=intent,
            route=self.route,
            success=all(s["ok"] for s in self.log),
            matched_template_id=self.matched_template_id,
            matched_plan_id=self.matched_plan_id,
            steps=self.log,
            llm_calls=self.llm_calls,
            duration_ms=self.duration_ms,
        )


def run(
    question: str,
    dataset: Dataset,
    library: FlowLibrary | None = None,
    generator: AIPlanGenerator | None = None,
    reviewer: AIReviewer | None = None,
    enable_review: bool = True,
) -> FullRunResult:
    """端到端运行（spec §6.2 / §7.5）

    Args:
        question: 用户问题
        dataset: Dataset
        library: Flow Library 实例（None 用默认）
        generator: fallback 时的 Plan 生成器（None 用 FakePlanGenerator）
        reviewer: AI Reviewer（None 用 FakeReviewer）
        enable_review: 全局开关；plan.reviewer_enabled 也需 True 才调

    Returns:
        FullRunResult
    """
    if library is None:
        library = FlowLibrary()
    if generator is None:
        generator = FakePlanGenerator()
    if reviewer is None:
        reviewer = FakeReviewer()

    t0 = time.perf_counter()
    r = route(question, dataset, library)
    llm_calls = 0
    matched_template_id: str | None = None
    matched_plan_id: str | None = None

    # 取 Plan
    if r.kind == "A" and r.template is not None:
        plan = Plan.from_dict(r.template.to_plan_dict())
        matched_template_id = r.template.template_id
    elif r.kind == "B" and r.plan is not None:
        plan = r.plan
        matched_plan_id = plan.plan_id
    else:
        # fallback：先查 library 是否有同 (fp, intent) 的 plan 复用
        # （避免每次 fallback 都生成新 plan_id 导致晋升计数失效）
        existing_plan = library.match_plan(dataset.schema_fingerprint, r.intent or "")
        if existing_plan is not None:
            plan = existing_plan
            llm_calls = 0  # 复用，不调 LLM
        else:
            plan = generator.generate(question, dataset, intent=r.intent)
            llm_calls = 1
            # 沉淀生成的 Plan 供下次复用（spec §7.1 B 轨）
            library.save_plan(plan)
        matched_plan_id = plan.plan_id

    # 执行
    inner = execute(plan, dataset)

    # Reviewer（plan.reviewer_enabled 且 enable_review 同时为 True）
    review_text: str | None = None
    if enable_review and plan.reviewer_enabled:
        review_text = reviewer.review(dataset, inner.charts, inner.log)

    duration_ms = int((time.perf_counter() - t0) * 1000)

    result = FullRunResult(
        df=inner.df,
        charts=inner.charts,
        log=inner.log,
        route=r.kind,
        review=review_text,
        plan_id=plan.plan_id,
        matched_template_id=matched_template_id,
        matched_plan_id=matched_plan_id,
        llm_calls=llm_calls,
        duration_ms=duration_ms,
    )

    # 沉淀 RunRecord
    run_rec = result.to_run_record(dataset.schema_fingerprint, r.intent or "")
    library.save_run(run_rec)

    # 自进化检查：每次运行后检查 (fp, intent, plan_id) 是否满足晋升条件
    # （B 轨复用的 plan 也应有机会晋升，不只 fallback 路径）
    if matched_plan_id and r.intent:
        Promoter(library=library).promote(
            dataset.schema_fingerprint, r.intent, matched_plan_id,
        )

    return result
