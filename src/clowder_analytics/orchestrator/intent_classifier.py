"""F002 P2: 意图分类器（spec §6.3）

规则 + 关键词起步，冷启动不上 embedding。
关键词覆盖 spec §6.3 提到的 5 类意图：TopN / 趋势 / 异常 / 对比 / 相关。

返回：意图字符串（与 Flow Library 中 template/plan 的 intent 字段对齐）
未命中返回 None（Router 据此走 fallback）
"""
from __future__ import annotations

# 关键词 → 意图映射（按 spec §6.3 5 类）
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "TopN 趋势分析": ["topn", "top ", "top30", "top10", "top5", "前10", "前30", "前5", "排名", "排行"],
    "异常归因": ["异常", "离群", "outlier", "偏离", "归因"],
    "趋势分析": ["趋势", "走势", "月度", "过去", "近", "时间序列", "时序"],
    "相关性分析": ["相关", "关联", "correlation", "关系"],
    "品类对比": ["对比", "比较", "vs", "之间差异"],
}


def classify_intent(question: str) -> str | None:
    """规则 + 关键词意图分类

    Args:
        question: 用户自然语言问题

    Returns:
        意图标签字符串；未命中返回 None
    """
    q = question.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                return intent
    return None
