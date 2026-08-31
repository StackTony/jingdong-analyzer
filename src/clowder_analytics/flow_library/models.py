"""F002 P2: Flow Library 数据模型（spec §7.1 / §7.2 / §7.5）

三种沉淀形态：
- A 轨 Template（YAML，spec §7.2）：稳定流程模板
- B 轨 Plan（JSON，spec §5.1）：复用过的执行序列
- 运行日志 RunRecord（JSONL，spec §7.5）：每次执行记录

P2 阶段存储用纯文件（templates/*.yaml / plans/*.json / runs/*.jsonl），
符合 spec §7.1"文件 + SQLite"中的"文件"层；SQLite 留 P5/P6 升级。

设计依据：
- spec §7.2：Template YAML 结构
- spec §7.5：RunRecord JSON 结构
- ADR-0001 D10：P1.5 已实现 Plan/Step/RunResult，本文件复用 Step
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from clowder_analytics.orchestrator.plan import Step


# ===== A 轨 Template =====

@dataclass
class Template:
    """A 轨模板（spec §7.2）

    YAML 序列化时字段顺序与 spec §7.2 一致。
    stability: candidate | stable | deprecated
    """
    template_id: str
    intent: str
    schema_fingerprint: str
    steps: list[Step]
    reviewer_enabled: bool = False
    fallback_strategy: str = "abort_on_first_error"
    created_at: str = ""
    promoted_from_plan_id: str | None = None
    stability: str = "candidate"
    confidence: float = 0.0  # 命中后供 Router 判断阈值

    def to_plan_dict(self) -> dict[str, Any]:
        """转 Plan 字典（供 executor 使用）"""
        return {
            "plan_id": f"tpl-{self.template_id}",
            "intent": self.intent,
            "schema_fingerprint": self.schema_fingerprint,
            "steps": [{"op": s.op, "args": s.args} for s in self.steps],
            "reviewer_enabled": self.reviewer_enabled,
            "fallback_strategy": self.fallback_strategy,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Template":
        return cls(
            template_id=d["template_id"],
            intent=d["intent"],
            schema_fingerprint=d["schema_fingerprint"],
            steps=[Step.from_dict(s) for s in d["steps"]],
            reviewer_enabled=d.get("reviewer_enabled", False),
            fallback_strategy=d.get("fallback_strategy", "abort_on_first_error"),
            created_at=d.get("created_at", ""),
            promoted_from_plan_id=d.get("promoted_from_plan_id"),
            stability=d.get("stability", "candidate"),
            confidence=d.get("confidence", 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "intent": self.intent,
            "schema_fingerprint": self.schema_fingerprint,
            "steps": [{"op": s.op, "args": s.args} for s in self.steps],
            "reviewer_enabled": self.reviewer_enabled,
            "fallback_strategy": self.fallback_strategy,
            "created_at": self.created_at,
            "promoted_from_plan_id": self.promoted_from_plan_id,
            "stability": self.stability,
            "confidence": self.confidence,
        }


# ===== RunRecord =====

@dataclass
class RunRecord:
    """运行日志条目（spec §7.5）

    每次执行后写入 flow_library/runs/*.jsonl，供命中率仪表盘与晋升机制查询。
    """
    schema_fingerprint: str
    intent: str
    route: str  # "A" | "B" | "fallback"
    success: bool
    matched_template_id: str | None = None
    matched_plan_id: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    user_adopted: bool | None = None
    user_correction: str | None = None
    llm_calls: int = 0
    duration_ms: int = 0
    run_id: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.run_id:
            self.run_id = uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "schema_fingerprint": self.schema_fingerprint,
            "intent": self.intent,
            "route": self.route,
            "matched_template_id": self.matched_template_id,
            "matched_plan_id": self.matched_plan_id,
            "steps": self.steps,
            "success": self.success,
            "user_adopted": self.user_adopted,
            "user_correction": self.user_correction,
            "llm_calls": self.llm_calls,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunRecord":
        return cls(
            schema_fingerprint=d["schema_fingerprint"],
            intent=d["intent"],
            route=d["route"],
            success=d["success"],
            matched_template_id=d.get("matched_template_id"),
            matched_plan_id=d.get("matched_plan_id"),
            steps=d.get("steps", []),
            user_adopted=d.get("user_adopted"),
            user_correction=d.get("user_correction"),
            llm_calls=d.get("llm_calls", 0),
            duration_ms=d.get("duration_ms", 0),
            run_id=d.get("run_id", ""),
            timestamp=d.get("timestamp", ""),
        )
