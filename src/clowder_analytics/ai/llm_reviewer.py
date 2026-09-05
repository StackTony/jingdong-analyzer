"""F002 P3+ 真实 LLM Reviewer（spec §5.2）

LLMReviewer 用 LLMProvider 生成三段式报告：
1. 构造 prompt：system（三段式结构说明）+ user（数据摘要 + 图表描述 + 执行日志）
2. 调 LLM，输出 Markdown
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.ai.base import AIReviewer
from clowder_analytics.ai.llm_provider import LLMProvider, get_prompt_section, load_provider


class LLMReviewer(AIReviewer):
    """用真实 LLM 生成三段式报告（spec §5.2）"""

    def __init__(self, provider: LLMProvider | None = None):
        self.provider = provider or load_provider()

    def review(
        self,
        dataset: Dataset,
        charts: list[Any],
        run_log: list[dict[str, Any]],
    ) -> str:
        system_prompt = get_prompt_section("reviewer")
        user_prompt = self._build_user_prompt(dataset, charts, run_log)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # max_tokens 从 provider.config 读（yaml 配置生效），不硬编码
        # 关羽 P2-1 同模式漏网修复：原硬编码 2000 覆盖 yaml 的 max_tokens
        config_max_tokens = getattr(getattr(self.provider, "config", None), "max_tokens", 2000)
        content = self.provider.chat(
            messages=messages,
            temperature=0.4,  # 报告稍宽容，允许稍创造性
            max_tokens=config_max_tokens,
        )
        return content

    def review_stream(
        self,
        dataset: Dataset,
        charts: list[Any],
        run_log: list[dict[str, Any]],
        on_delta: Any = None,
    ) -> str:
        """流式生成三段式报告（G18）：逐 chunk 回调 on_delta，返回全文

        provider.chat_stream 逐片段产出（OpenAI 兼容 stream=True）；
        不支持流式的 provider（只有 chat）走 base 默认回落一次性返回。
        prompt 构造与 review() 完全同构（_build_user_prompt 复用）。
        """
        system_prompt = get_prompt_section("reviewer")
        user_prompt = self._build_user_prompt(dataset, charts, run_log)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        config_max_tokens = getattr(getattr(self.provider, "config", None), "max_tokens", 2000)
        parts: list[str] = []
        for chunk in self.provider.chat_stream(
            messages=messages,
            temperature=0.4,
            max_tokens=config_max_tokens,
        ):
            parts.append(chunk)
            if on_delta is not None:
                on_delta(chunk)
        return "".join(parts)

    def _build_user_prompt(
        self, dataset: Dataset, charts: list[Any], run_log: list[dict[str, Any]],
    ) -> str:
        df = dataset.df

        # 数据摘要
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        stats_block = ""
        if numeric_cols:
            stats_lines = []
            for c in numeric_cols[:5]:
                s = df[c].dropna()
                if len(s) > 0:
                    stats_lines.append(
                        f"- {c}: mean={s.mean():.2f}, std={s.std():.2f}, "
                        f"min={s.min():.2f}, max={s.max():.2f}, n={len(s)}"
                    )
            stats_block = "\n".join(stats_lines)

        # 前 10 行
        preview = df.head(10).to_string()

        # 图表描述
        charts_block = ""
        if charts:
            chart_lines = []
            for i, c in enumerate(charts):
                chart_lines.append(
                    f"- 图 {i+1}: type={c.type}, title={c.title}, x={c.x}, y={c.y}"
                )
            charts_block = "\n".join(chart_lines)

        # 执行日志
        log_lines = []
        for i, entry in enumerate(run_log):
            status = "OK" if entry.get("ok") else "FAIL"
            err = entry.get("err", "")
            log_lines.append(f"  [{i+1}] {entry.get('step', '?')} {status} {err}")
        log_block = "\n".join(log_lines) if log_lines else "（无）"

        return f"""## 数据摘要

行数: {len(df)}
列数: {len(df.columns)}
列: {', '.join(df.columns)}

数值统计:
{stats_block or "无数值列"}

前 10 行:
{preview}

## 图表

{charts_block or "无图表"}

## 执行日志

{log_block}

## 请生成三段式报告

按 system 提示的结构，输出 Markdown：
- ## 异常解释
- ## 趋势点睛
- ## 建议下一步
"""
