"""F002 P3: AI Fake 实现（确定性，供测试 / P5 CLI 兜底）

FakePlanGenerator：按 intent 关键词路由到内置 Plan 模板
FakeReviewer：基于 run_log + 数据统计生成确定性三段式报告

不调真实 LLM，保证测试稳定可重复。
真实 LLM provider 接入见 providers.py（后续迭代）。
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pandas as pd

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.ai.base import AIPlanGenerator, AIReviewer
from clowder_analytics.orchestrator.plan import Plan, Step


# ===== FakePlanGenerator =====

class FakePlanGenerator(AIPlanGenerator):
    """按 intent 关键词路由到内置 Plan 模板

    内置 5 个意图的固定 Plan（与 spec §6.3 五类意图对齐）：
    - TopN 趋势分析: normalize → aggregate → topn
    - 异常归因: anomaly_attribution
    - 趋势分析: trend
    - 相关性分析: correlation
    - 品类对比: aggregate
    """

    def generate(self, question: str, dataset: Dataset, intent: str | None = None) -> Plan:
        if intent is None:
            # 兜底：从 question 简单推断
            intent = self._guess_intent(question)

        # 取数据列，猜测 value_col / group_by
        cols = list(dataset.df.columns)
        value_col = self._pick_value_col(dataset.df, cols)
        group_by = self._pick_group_col(dataset.df, cols)

        plan_id = f"fake-{uuid4().hex[:8]}"
        steps = self._build_steps(intent, group_by, value_col)

        return Plan(
            plan_id=plan_id,
            intent=intent,
            schema_fingerprint=dataset.schema_fingerprint,
            steps=steps,
            reviewer_enabled=False,  # Fake 默认不调 reviewer
            fallback_strategy="abort_on_first_error",
        )

    def _guess_intent(self, question: str) -> str:
        q = question.lower()
        if "top" in q or "排名" in q or "排行" in q:
            return "TopN 趋势分析"
        if "异常" in q or "离群" in q:
            return "异常归因"
        if "趋势" in q or "走势" in q:
            return "趋势分析"
        if "相关" in q:
            return "相关性分析"
        return "TopN 趋势分析"

    def _pick_value_col(self, df: pd.DataFrame, cols: list[str]) -> str:
        """选数值列作 value_col（偏好 sales/price/count 等）"""
        hints = ["sales", "price", "count", "amount", "value", "qty"]
        for h in hints:
            for c in cols:
                if h in c.lower() and pd.api.types.is_numeric_dtype(df[c]):
                    return c
        # 兜底：第一个数值列
        for c in cols:
            if pd.api.types.is_numeric_dtype(df[c]):
                return c
        return cols[-1] if cols else "value"

    def _pick_group_col(self, df: pd.DataFrame, cols: list[str]) -> list[str]:
        """选文本列作 group_by（偏好 brand/name/category 等）"""
        hints = ["brand", "name", "category", "cat", "label"]
        for h in hints:
            for c in cols:
                if h in c.lower() and not pd.api.types.is_numeric_dtype(df[c]):
                    return [c]
        # 兜底：第一个非数值列
        for c in cols:
            if not pd.api.types.is_numeric_dtype(df[c]):
                return [c]
        return [cols[0]] if cols else ["_group"]

    def _build_steps(self, intent: str, group_by: list[str], value_col: str) -> list[Step]:
        if intent == "TopN 趋势分析":
            return [
                Step(op="clean.normalize_text", args={"columns": group_by, "ops": ["trim", "lower"]}),
                Step(op="model.aggregate", args={"group_by": group_by, "agg": {value_col: "sum"}}),
                Step(op="model.topn", args={
                    "group_by": group_by, "value_col": value_col, "n": 30, "rank_by": "value",
                }),
            ]
        if intent == "异常归因":
            return [
                Step(op="model.anomaly_attribution", args={
                    "value_col": value_col, "group_by": group_by, "baseline": "mean",
                }),
            ]
        if intent == "趋势分析":
            # 趋势需要时间列；fake 假设 df 含 month/date 等
            return [
                Step(op="model.trend", args={
                    "time_col": group_by[0] if group_by else "month",
                    "value_col": value_col, "freq": "M",
                }),
            ]
        if intent == "相关性分析":
            return [
                Step(op="model.correlation", args={"columns": [value_col], "method": "pearson"}),
            ]
        if intent == "品类对比":
            return [
                Step(op="model.aggregate", args={"group_by": group_by, "agg": {value_col: "sum"}}),
            ]
        # 兜底
        return [Step(op="model.aggregate", args={"group_by": group_by, "agg": {value_col: "sum"}})]


# ===== FakeReviewer =====

class FakeReviewer(AIReviewer):
    """确定性三段式报告生成器

    基于 run_log + 数据统计，不调 LLM。
    输出 Markdown 三段：异常解释 / 趋势点睛 / 建议下一步
    """

    def review(
        self,
        dataset: Dataset,
        charts: list[Any],
        run_log: list[dict[str, Any]],
    ) -> str:
        df = dataset.df
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

        # === 异常解释 ===
        anomaly_section = self._anomaly_section(df, numeric_cols)

        # === 趋势点睛 ===
        trend_section = self._trend_section(df, numeric_cols, charts)

        # === 建议下一步 ===
        next_section = self._next_section(df, numeric_cols, run_log)

        return f"""## 异常解释

{anomaly_section}

## 趋势点睛

{trend_section}

## 建议下一步

{next_section}
"""

    def _anomaly_section(self, df: pd.DataFrame, numeric_cols: list[str]) -> str:
        if not numeric_cols:
            return "未检测到数值列，无法做异常分析。"
        col = numeric_cols[0]
        s = df[col].dropna()
        if len(s) < 4:
            return f"列 `{col}` 数据量不足（{len(s)} 行），异常检测不可靠。"
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = s[(s < lo) | (s > hi)]
        if len(outliers) == 0:
            return f"列 `{col}` 未检测到 IQR 异常值（区间 [{lo:.2f}, {hi:.2f}]）。"
        lines = [f"列 `{col}` 检测到 {len(outliers)} 个 IQR 异常值（区间 [{lo:.2f}, {hi:.2f}]）："]
        for idx, val in outliers.head(5).items():
            direction = "偏高" if val > hi else "偏低"
            lines.append(f"  - 行 {idx}: {val:.2f}（{direction}）")
        return "\n".join(lines)

    def _trend_section(self, df: pd.DataFrame, numeric_cols: list[str], charts: list[Any]) -> str:
        if not numeric_cols:
            return "无数值列，无法识别趋势。"
        col = numeric_cols[0]
        s = df[col].dropna()
        if len(s) < 2:
            return f"列 `{col}` 数据量不足，无法识别趋势。"
        mean_val = s.mean()
        max_val, min_val = s.max(), s.min()
        return (
            f"列 `{col}` 均值 {mean_val:.2f}，"
            f"范围 [{min_val:.2f}, {max_val:.2f}]，"
            f"极差 {max_val - min_val:.2f}。"
            f"生成图表 {len(charts)} 个。"
        )

    def _next_section(self, df: pd.DataFrame, numeric_cols: list[str], run_log: list[dict[str, Any]]) -> str:
        ok_count = sum(1 for e in run_log if e.get("ok"))
        fail_count = len(run_log) - ok_count
        lines = [f"执行日志：{ok_count} 步成功，{fail_count} 步失败。"]
        if fail_count > 0:
            lines.append("- 建议先排查失败步骤的 args 是否匹配 schema。")
        if len(numeric_cols) >= 2:
            lines.append(f"- 可尝试相关性分析（{', '.join(numeric_cols[:3])}）。")
        if len(df) > 10:
            lines.append("- 数据量充足，可考虑聚类或更细粒度 TopN。")
        return "\n".join(lines)
