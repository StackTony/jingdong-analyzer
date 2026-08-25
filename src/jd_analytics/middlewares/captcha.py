"""
验证码检测中间件（spec §3.5 极简版）

检测到验证码 → 写入 retry_queue + 跳过该请求
（不绕过验证码——spec §1.5 红线）
"""
from __future__ import annotations

import logging
import re

from scrapy.exceptions import IgnoreRequest

logger = logging.getLogger(__name__)

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
    """检测到验证码立即跳过（不绕过）"""

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_response(self, request, response, spider):
        if not response.text:
            return response

        if self._is_captcha(response.text):
            logger.warning(
                f"Captcha detected, skipping URL: {request.url}"
            )

            # 写入 retry_queue（spec §8.3）
            try:
                from jd_analytics.pipelines.retry import enqueue_retry
                enqueue_retry(
                    request.url,
                    request.meta.get("batch_id"),
                    "captcha",
                )
            except Exception as e:
                logger.error(f"Failed to enqueue retry: {e}")

            raise IgnoreRequest(f"Captcha detected: {request.url}")

        return response

    @staticmethod
    def _is_captcha(text: str) -> bool:
        return any(p.search(text) for p in CAPTCHA_PATTERNS)
