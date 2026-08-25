"""
反爬栈 Layer 4: 检测层 - 验证码检测（spec §3.5）

检测到验证码立即暂停该 IP，不硬闯（避免永久 ban）。
"""
from __future__ import annotations

import logging
import re

from scrapy.exceptions import IgnoreRequest

logger = logging.getLogger(__name__)

# 京东验证码特征
CAPTCHA_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r'id="captcha"',
        r'class="JDJRV-bigimg"',
        r'/captcha/',
        r'请输入验证码',
        r'滑动验证',
        r'人机验证',
        r'verify\.jd\.com',
    ]
]


class CaptchaDetectMiddleware:
    """检测到验证码立即暂停该 IP，切换到其他 IP"""

    def __init__(self, pause_minutes: int = 30):
        self.pause_minutes = pause_minutes

    @classmethod
    def from_crawler(cls, crawler):
        return cls(pause_minutes=30)

    def process_response(self, request, response, spider):
        if not response.text:
            return response

        if self._is_captcha(response.text):
            proxy_obj = request.meta.get("proxy_obj")
            ip = proxy_obj.ip if proxy_obj else "unknown"
            logger.warning(
                f"Captcha detected, IP paused for {self.pause_minutes}min: {ip}"
            )

            if proxy_obj and hasattr(spider, "proxy_pool"):
                spider.proxy_pool.report_failure(proxy_obj.ip, "captcha")

            # 该 URL 写入 retry_queue（spec §8.3）
            self._enqueue_retry(request.url, request.meta.get("batch_id"), "captcha")

            raise IgnoreRequest(f"Captcha detected, IP paused: {ip}")

        return response

    @staticmethod
    def _is_captcha(text: str) -> bool:
        return any(p.search(text) for p in CAPTCHA_PATTERNS)

    @staticmethod
    def _enqueue_retry(url: str, batch_id: str | None, reason: str) -> None:
        """写入 retry_queue（实际实现由 RetryPipeline 处理）"""
        from jd_analytics.pipelines.retry import enqueue_retry
        enqueue_retry(url, batch_id, reason)
