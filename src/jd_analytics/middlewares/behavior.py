"""
反爬栈 Layer 3: 行为层中间件（spec §3.4）

鼠标轨迹 + 滚动延迟 + 停留时间 + 路径模拟。
"""
from __future__ import annotations

import random
import time
import logging

logger = logging.getLogger(__name__)


class BehaviorMiddleware:
    """行为模拟：随机延迟 + 不直接跳详情 + 鼠标/滚动模拟"""

    def __init__(self, direct_ratio: float = 0.3):
        self.direct_ratio = direct_ratio  # 直接跳详情的比例

    @classmethod
    def from_crawler(cls, crawler):
        return cls(direct_ratio=0.3)

    def process_request(self, request, spider):
        # 1. 随机延迟：90% 1-5s, 10% 10-30s（长尾）
        delay = self._weighted_delay()
        time.sleep(delay)
        request.meta["behavior_delay"] = delay

        # 2. 不直接跳详情：70% 概率先访问列表页（meta direct=True 才直跳）
        if random.random() < (1 - self.direct_ratio) and not request.meta.get("direct"):
            request.meta["via_list_page"] = True
            # 实际重定向到列表页由 spider 实现，这里只标记

        # 3. Playwright 页面的鼠标/滚动模拟
        if request.meta.get("playwright"):
            request.meta.setdefault("playwright_page_methods", []).extend([
                {"method": "mouse.move", "args": self._random_offset()},
                {"method": "mouse.wheel", "args": [0, random.randint(100, 800)]},
                {"method": "wait_for_timeout",
                 "args": [random.randint(5000, 30000)]},
            ])

    @staticmethod
    def _weighted_delay() -> float:
        """90% 1-5s + 10% 10-30s 长尾"""
        if random.random() < 0.9:
            return random.uniform(1, 5)
        return random.uniform(10, 30)

    @staticmethod
    def _random_offset() -> list[int]:
        return [random.randint(100, 800), random.randint(100, 600)]
