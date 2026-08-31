"""F002 P1.5: Plan 数据模型 + OpError（spec §5.1 / §6.1-6.2）

Plan 是 B 轨的声明式执行序列，也是 A 轨模板 to_plan() 后的统一形式。
P1.5 阶段不接 LLM，固定 Plan 验证"Plan + op + 执行器"链路通。

设计依据：
- spec §5.1：Plan JSON 结构
- spec §6.2：Executor 执行逻辑
- ADR-0001 D10：P1.5 在调 LLM 前先验证链路
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class OpError(Exception):
    """原子能力执行失败（spec §4.1：失败抛 OpError，不吞异常）

    Executor 捕获后写入 run_log，按 fallback_strategy 决定是否继续。
    """


@dataclass
class Step:
    """Plan 的一步：op 名 + args

    op 命名约定（spec §5.1）：
        - "clean.<name>"：cleaner 原子能力
        - "model.<name>"：modeler 原子能力
        - "viz.<name>"：visualizer 原子能力（一般不直接出现，model op 自带 chart）
    """
    op: str
    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        return cls(op=d["op"], args=d.get("args", {}))


@dataclass
class Plan:
    """B 轨 Plan / A 轨模板 to_plan() 后的统一形式（spec §5.1）

    Attributes:
        plan_id: 自生成 uuid，便于沉淀追溯
        intent: 意图标签（"TopN 趋势分析" / "异常归因" 等）
        schema_fingerprint: 匹配的 schema 指纹（P1.5 固定 Plan 可空）
        steps: Step 序列
        reviewer_enabled: 是否调 AI Reviewer（P1.5 不接，默认 False）
        fallback_strategy: "abort_on_first_error" | "continue_on_error"
    """
    plan_id: str
    intent: str
    steps: list[Step]
    schema_fingerprint: str = ""
    reviewer_enabled: bool = False
    fallback_strategy: str = "abort_on_first_error"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Plan":
        return cls(
            plan_id=d["plan_id"],
            intent=d["intent"],
            steps=[Step.from_dict(s) for s in d["steps"]],
            schema_fingerprint=d.get("schema_fingerprint", ""),
            reviewer_enabled=d.get("reviewer_enabled", False),
            fallback_strategy=d.get("fallback_strategy", "abort_on_first_error"),
        )


@dataclass
class RunResult:
    """Plan 执行结果（spec §6.2 RunResult）

    Attributes:
        df: 终态 DataFrame
        charts: 收集到的 ChartSpec 列表（来自 model op）
        log: run_log，每条 {"step": op_name, "ok": bool, "report"/"err"}
        route: 路由标记（"A"/"B"/"fallback"），P1.5 固定走 "B"
        review: AI Reviewer 文字报告（P1.5 不接，None）
        plan_id: 执行的 Plan id
    """
    df: Any
    charts: list[Any] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    route: str = "B"
    review: str | None = None
    plan_id: str = ""
