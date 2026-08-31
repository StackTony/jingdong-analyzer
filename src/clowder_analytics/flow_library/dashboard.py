"""F002 P6: 仪表盘统计（spec §7.6 / AC-12）

compute_stats(library) -> Stats
format_stats(stats) -> str（CLI 友好输出）

可观测：
- A 命中率 / B 命中率 / 兜底率
- 平均 LLM 调用数
- 候选模板队列长度
- Top 5 高频 intent
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from clowder_analytics.flow_library.store import FlowLibrary


@dataclass
class Stats:
    """仪表盘统计数据"""
    total_runs: int = 0
    a_hits: int = 0
    b_hits: int = 0
    fallback_hits: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    a_rate: float = 0.0
    b_rate: float = 0.0
    fallback_rate: float = 0.0
    avg_llm_calls: float = 0.0
    total_llm_calls: int = 0
    candidate_count: int = 0
    stable_count: int = 0
    deprecated_count: int = 0
    top_intents: list[tuple[str, int]] = field(default_factory=list)


def compute_stats(library: FlowLibrary, recent_n: int | None = None) -> Stats:
    """计算统计指标

    Args:
        library: Flow Library
        recent_n: 仅看最近 N 条（None=全部）
    """
    runs = library.list_runs(limit=recent_n)
    templates = library.list_templates()

    total = len(runs)
    a = sum(1 for r in runs if r.route == "A")
    b = sum(1 for r in runs if r.route == "B")
    fb = sum(1 for r in runs if r.route == "fallback")
    success = sum(1 for r in runs if r.success)
    llm_total = sum(r.llm_calls for r in runs)

    intent_counter = Counter(r.intent for r in runs if r.intent)
    top_intents = intent_counter.most_common(5)

    return Stats(
        total_runs=total,
        a_hits=a, b_hits=b, fallback_hits=fb,
        success_count=success,
        success_rate=(success / total * 100) if total else 0.0,
        a_rate=(a / total * 100) if total else 0.0,
        b_rate=(b / total * 100) if total else 0.0,
        fallback_rate=(fb / total * 100) if total else 0.0,
        avg_llm_calls=(llm_total / total) if total else 0.0,
        total_llm_calls=llm_total,
        candidate_count=sum(1 for t in templates if t.stability == "candidate"),
        stable_count=sum(1 for t in templates if t.stability == "stable"),
        deprecated_count=sum(1 for t in templates if t.stability == "deprecated"),
        top_intents=top_intents,
    )


def format_stats(stats: Stats) -> str:
    """格式化为 CLI 友好输出"""
    lines = [
        "=== Flow Library 统计 ===",
        f"总运行次数: {stats.total_runs}",
        f"A 轨命中: {stats.a_hits} ({stats.a_rate:.1f}%)",
        f"B 轨命中: {stats.b_hits} ({stats.b_rate:.1f}%)",
        f"兜底: {stats.fallback_hits} ({stats.fallback_rate:.1f}%)",
        f"成功率: {stats.success_count}/{stats.total_runs} ({stats.success_rate:.1f}%)",
        f"LLM 调用总数: {stats.total_llm_calls}"
        f"（平均 {stats.avg_llm_calls:.2f} 次/运行）",
        f"模板统计: stable={stats.stable_count}, "
        f"candidate={stats.candidate_count}, "
        f"deprecated={stats.deprecated_count}",
    ]
    if stats.top_intents:
        lines.append("Top 5 高频 intent:")
        for intent, count in stats.top_intents:
            lines.append(f"  - {intent}: {count} 次")
    return "\n".join(lines)
