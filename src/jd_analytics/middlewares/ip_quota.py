"""
反爬栈 Layer 5: 调度层 - 单 IP 日请求上限（spec §3.7）

避免单 IP 短期高请求触发封禁。试爬前默认 800，试爬后校准。
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IPQuotaMiddleware:
    """单 IP 日请求上限"""

    def __init__(self, daily_limit: int = 800):
        self.daily_limit = daily_limit
        self.counter: dict[str, int] = defaultdict(int)
        self.reset_at = self._next_midnight()

    @classmethod
    def from_crawler(cls, crawler):
        from jd_analytics.settings import DAILY_LIMIT_PER_IP
        return cls(daily_limit=DAILY_LIMIT_PER_IP)

    def process_request(self, request, spider):
        self._maybe_reset()

        proxy_obj = request.meta.get("proxy_obj")
        if not proxy_obj:
            return

        ip = proxy_obj.ip
        if self.counter[ip] >= self.daily_limit:
            logger.info(f"IP {ip} hit daily limit {self.daily_limit}, switching")
            # 标记此 proxy 本次不可用，由 ProxyRotationMiddleware 选新的
            request.meta["proxy_obj"] = None
            request.meta["proxy"] = None
            return

        self.counter[ip] += 1

    def _maybe_reset(self) -> None:
        if time.time() > self.reset_at:
            self.counter.clear()
            self.reset_at = self._next_midnight()

    @staticmethod
    def _next_midnight() -> float:
        tomorrow = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        return tomorrow.timestamp()
