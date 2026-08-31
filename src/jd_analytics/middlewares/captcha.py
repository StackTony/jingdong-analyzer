"""
验证码检测（spec §3.5 + F001-ocr-route P0-1 修复）

DrissionPage 路线下，captcha 检测从 Scrapy 中间件改造为**纯函数**，
在 DrissionSpider 每次 `dp.get()` 后调用 `detect_captcha()`。

检测到验证码 → 写入 retry_queue + 跳过该请求
（不绕过验证码——spec §1.5 红线）

保留 CaptchaDetectMiddleware 类兼容 Scrapy 路线。
"""
from __future__ import annotations

import logging
import re
from typing import Any

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
        r'JDJRV',
        r'sliderVerification',
        r'nc_1_n1z',  # 京东滑块元素 ID
    ]
]


def detect_captcha(dp: Any) -> dict[str, Any]:
    """检测当前 DrissionPage 页面是否含验证码

    在每次 `dp.get()` 后调用。返回检测结果：
    {
        "is_captcha": bool,
        "pattern": str,  # 匹配到的正则
    }
    """
    result = {"is_captcha": False, "pattern": ""}

    try:
        html = ""
        if hasattr(dp, "html"):
            html = dp.html
        elif hasattr(dp, "page_source"):
            html = dp.page_source

        if not html:
            return result

        for pattern in CAPTCHA_PATTERNS:
            if pattern.search(html):
                result["is_captcha"] = True
                result["pattern"] = pattern.pattern
                logger.warning(
                    f"Captcha detected: pattern={pattern.pattern}"
                )
                return result

    except Exception as e:
        logger.warning(f"Captcha detection failed: {e}")

    return result


def handle_captcha(
    dp: Any,
    url: str,
    batch_id: str,
    captcha_result: dict[str, Any],
) -> str:
    """处理验证码：写入 retry_queue + 跳过

    Returns:
        "skip" — 调用方跳过该 URL
    """
    logger.warning(
        f"Captcha detected, skipping URL: {url} "
        f"(pattern={captcha_result.get('pattern')})"
    )

    try:
        from jd_analytics.pipelines.retry import enqueue_retry
        enqueue_retry(url, batch_id, "captcha")
    except Exception as e:
        logger.error(f"Failed to enqueue retry: {e}")

    return "skip"


# ===== Scrapy middleware 兼容层 =====

try:
    from scrapy.exceptions import IgnoreRequest

    class CaptchaDetectMiddleware:
        """验证码检测中间件（Scrapy 路线兼容层）

        DrissionPage 路线下不用此类——改用 detect_captcha() 纯函数。
        """

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

except ImportError:
    pass
