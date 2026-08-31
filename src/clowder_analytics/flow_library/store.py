"""F002 P2: Flow Library 存储 + 匹配（spec §7）

文件存储：
- templates/*.yaml（spec §7.2 YAML 结构）
- plans/*.json（spec §5.1 JSON 结构）
- runs/runs.jsonl（spec §7.5 追加模式）

匹配策略（P2）：
- A 轨 match_template：精确 fp + intent；stable 优先，candidate 兜底，deprecated 跳过
- B 轨 match_plan：精确 fp + intent
- 相似度匹配留 P4 升级

设计依据：spec §7.1 / §7.2 / §7.4
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from clowder_analytics.flow_library.models import RunRecord, Template
from clowder_analytics.orchestrator.plan import Plan


# 命中阈值（spec §6.1 THRESHOLD_A/B；P2 先用固定值，P6 调参）
THRESHOLD_A = 0.5
THRESHOLD_B = 0.3


class FlowLibrary:
    """Flow Library 文件存储 + 匹配

    用法：
        lib = FlowLibrary(base_dir=Path("flow_library_data"))
        lib.save_template(tpl)
        matched = lib.match_template(fp, intent)
    """

    def __init__(self, base_dir: Path | str | None = None):
        if base_dir is None:
            # 默认放包内 flow_library_data/（便于打包冷启动模板）
            import clowder_analytics
            pkg_root = Path(clowder_analytics.__file__).parent
            base_dir = pkg_root / "flow_library_data"
        self.base_dir = Path(base_dir)
        self.templates_dir = self.base_dir / "templates"
        self.plans_dir = self.base_dir / "plans"
        self.runs_dir = self.base_dir / "runs"
        for d in (self.templates_dir, self.plans_dir, self.runs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ===== Template CRUD =====

    def save_template(self, tpl: Template) -> Path:
        """写 templates/<template_id>.yaml"""
        path = self.templates_dir / f"{tpl.template_id}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(tpl.to_dict(), f, allow_unicode=True, sort_keys=False)
        return path

    def load_template(self, template_id: str) -> Template | None:
        path = self.templates_dir / f"{template_id}.yaml"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return Template.from_dict(data)

    def list_templates(self) -> list[Template]:
        return [
            Template.from_dict(yaml.safe_load(open(p, encoding="utf-8")))
            for p in sorted(self.templates_dir.glob("*.yaml"))
        ]

    # ===== Plan CRUD =====

    def save_plan(self, plan: Plan) -> Path:
        path = self.plans_dir / f"{plan.plan_id}.json"
        # Plan 没有 to_dict，手工序列化
        payload = {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "schema_fingerprint": plan.schema_fingerprint,
            "steps": [{"op": s.op, "args": s.args} for s in plan.steps],
            "reviewer_enabled": plan.reviewer_enabled,
            "fallback_strategy": plan.fallback_strategy,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def load_plan(self, plan_id: str) -> Plan | None:
        path = self.plans_dir / f"{plan_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return Plan.from_dict(data)

    def list_plans(self) -> list[Plan]:
        out = []
        for p in sorted(self.plans_dir.glob("*.json")):
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            out.append(Plan.from_dict(data))
        return out

    # ===== RunRecord CRUD =====

    def save_run(self, rec: RunRecord) -> Path:
        """追加到 runs/runs.jsonl（spec §7.5）"""
        path = self.runs_dir / "runs.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
        return path

    def list_runs(self, limit: int | None = None) -> list[RunRecord]:
        path = self.runs_dir / "runs.jsonl"
        if not path.exists():
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(RunRecord.from_dict(json.loads(line)))
        if limit:
            out = out[-limit:]
        return out

    # ===== Matcher =====

    def match_template(self, schema_fingerprint: str, intent: str) -> Template | None:
        """A 轨匹配（spec §6.1 step 1）

        优先级：stable > candidate > （deprecated 跳过）
        精确匹配 schema_fingerprint + intent
        """
        candidates = [
            t for t in self.list_templates()
            if t.schema_fingerprint == schema_fingerprint
            and t.intent == intent
            and t.stability != "deprecated"
        ]
        if not candidates:
            return None
        # stable 优先
        stable = [t for t in candidates if t.stability == "stable"]
        if stable:
            # 多个 stable 取 confidence 最高
            return max(stable, key=lambda t: t.confidence)
        # 无 stable 时 candidate 兜底
        candidates.sort(key=lambda t: t.confidence, reverse=True)
        return candidates[0]

    def match_plan(self, schema_fingerprint: str, intent: str) -> Plan | None:
        """B 轨匹配（spec §6.1 step 2）

        P2 精确匹配；相似度留 P4
        """
        for p in self.list_plans():
            if p.schema_fingerprint == schema_fingerprint and p.intent == intent:
                return p
        return None
