"""F002 P3: AI Plan 生成器 + Reviewer 抽象（spec §5.1 / §5.2）

P3 阶段策略：
- 定义抽象接口（AIPlanGenerator / AIReviewer）
- 提供确定性 Fake 实现（FakePlanGenerator / FakeReviewer），供 P3 测试与 P5 CLI 兜底
- 真实 LLM provider 接入（GLM-4.6 / OpenAI 等）留后续迭代——
  P3 关键是接口对齐 + 三段式报告结构，LLM 调用细节是工程问题不阻塞 P4

设计依据：spec §5.1 / §5.2 / §5.3
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from clowder_analytics.adapters.base import Dataset
from clowder_analytics.orchestrator.plan import Plan, Step


# ===== AIPlanGenerator 抽象 =====

class AIPlanGenerator(ABC):
    """AI Plan 生成器抽象（spec §5.1）

    触发：Router fallback 时调用
    输入：question + Dataset + 原子能力清单
    输出：Plan（B 轨 JSON 结构）
    """

    @abstractmethod
    def generate(self, question: str, dataset: Dataset, intent: str | None = None) -> Plan:
        """生成 Plan

        Args:
            question: 用户问题
            dataset: Dataset（含 schema 摘要 + 样本）
            intent: 已分类的意图（None 时 generator 自行推断）

        Returns:
            Plan 对象
        """
        raise NotImplementedError


# ===== AIReviewer 抽象 =====

class AIReviewer(ABC):
    """AI Reviewer 抽象（spec §5.2）

    触发：Plan 执行完后，reviewer_enabled=True 时调用
    输入：Dataset + charts + run_log
    输出：三段式文字报告（异常解释 / 趋势点睛 / 建议下一步）
    """

    @abstractmethod
    def review(
        self,
        dataset: Dataset,
        charts: list[Any],
        run_log: list[dict[str, Any]],
    ) -> str:
        """生成三段式文字报告

        Returns:
            Markdown 文字报告，含三段：
            - 异常解释
            - 趋势点睛
            - 建议下一步
        """
        raise NotImplementedError
