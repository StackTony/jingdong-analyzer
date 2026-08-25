"""
单 IP 日请求配额（spec §3.7 极简版）

铲屎官拍板：单 IP 慢爬模式。
单 IP 日请求上限保守取 1500，防止被京东封禁。
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IPQuotaMiddleware:
    """单 IP 日请求上限（单 IP 模式下等于全局上限）"""

    def __init__(self, daily_limit: int = 1500):
        self.daily_limit = daily_limit
        self.counter: int = 0
        self.reset_at = self._next_midnight()

    @classmethod
    def from_crawler(cls, crawler):
        from jd_analytics.settings import DAILY_LIMIT_PER_IP
        return cls(daily_limit=DAILY_LIMIT_PER_IP)

    def process_request(self, request, spider):
        self._maybe_reset()

        if self.counter >= self.daily_limit:
            spider.logger.warning(
                f"Daily limit {self.daily_limit} reached, pausing until midnight"
            )
            # 计算到午夜还需等待多久
            wait_seconds = max(self.reset_at - time.time(), 0)
            if wait_seconds > 0 and wait_seconds < 12 * 3600:
                logger.info(f"Sleeping {wait_seconds:.0f}s until midnight reset")
                time.sleep(wait_seconds + 60)
                self._maybe_reset()
            else:
                # 异常情况，跳过这个请求
                from scrapy.exceptions import IgnoreRequest
                raise IgnoreRequest(f"Daily limit {self.daily_limit} exceeded")

        self.counter += 1

    def _maybe_reset(self) -> None:
        if time.time() > self.reset_at:
            self.counter = 0
            self.reset_at = self._next_midnight()
            logger.info("Daily counter reset")

    @staticmethod
    def _next_midnight() -> float:
        tomorrow = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        return tomorrow.timestamp()
