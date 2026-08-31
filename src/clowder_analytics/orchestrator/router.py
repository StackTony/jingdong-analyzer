"""F002 P2: Router 双轨调度（spec §6.1）

route(question, dataset, library) -> Route

三层匹配：
1. A 轨：match_template（fp + intent，stable 优先）→ Route(kind="A", template=...)
2. B 轨：match_plan（fp + intent）→ Route(kind="B", plan=...)
3. fallback：Route(kind="fallback", generate=True)——P2 阶段不接 LLM，
   P3 接 LLM 时 generate=True 触发 AI Plan Generator

设计依据：spec §6.1 / §6.3
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.flow_library.models import Template
from clowder_analytics.flow_library.store import THRESHOLD_A, THRESHOLD_B, FlowLibrary
from clowder_analytics.orchestrator.intent_classifier import classify_intent
from clowder_analytics.orchestrator.plan import Plan


@dataclass
class Route:
    """路由结果（spec §6.1 Route）

    kind: "A" | "B" | "fallback"
    template: A 轨命中的 Template（kind=A 时非空）
    plan: B 轨命中的 Plan（kind=B 时非空）
    generate: 兜底时 True（触发 AI Plan Generator）
    intent: 分类出的意图（None 时表示未识别）
    """
    kind: str
    template: Template | None = None
    plan: Plan | None = None
    generate: bool = False
    intent: str | None = None


def route(
    question: str,
    dataset: Dataset,
    library: FlowLibrary | None = None,
) -> Route:
    """双轨调度（spec §6.1）

    Args:
        question: 用户问题
        dataset: Dataset（取 schema_fingerprint）
        library: FlowLibrary 实例，None 时用默认实例

    Returns:
        Route
    """
    if library is None:
        library = FlowLibrary()

    intent = classify_intent(question)
    fp = dataset.schema_fingerprint

    if intent is None:
        return Route(kind="fallback", generate=True, intent=None)

    # 1. A 轨
    tpl = library.match_template(fp, intent)
    if tpl is not None and tpl.confidence >= THRESHOLD_A:
        return Route(kind="A", template=tpl, intent=intent)

    # 2. B 轨
    plan = library.match_plan(fp, intent)
    if plan is not None:
        # B 轨 Plan 暂无 confidence 字段，命中即走
        return Route(kind="B", plan=plan, intent=intent)

    # 3. fallback
    return Route(kind="fallback", generate=True, intent=intent)
