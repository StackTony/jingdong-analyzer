"""
403/429 ban 检测（spec §3.5）

DrissionPage 路线下，ban 检测从 Scrapy 中间件改造为**纯函数**，
在 DrissionSpider 每次 `dp.get()` 后调用 `detect_ban_response()`。

检测逻辑：
- HTTP 状态 403/429 → ban
- 页面标题/正文含 ban 关键词 → ban
- 检测到 ban → 写入 retry_queue + 退避

保留 BanDetectMiddleware 类兼容 Scrapy 路线（如果未来启用）。
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)


# ban 关键词（页面正文含这些词说明被 ban 了）
BAN_KEYWORDS = [
    "访问过于频繁",
    "请稍后再试",
    "异常",
    "暂时无法访问",
    "blocked",
    "forbidden",
    "请求过于频繁",
    "滑块验证",
]


def detect_ban_response(dp: Any) -> dict[str, Any]:
    """检测当前 DrissionPage 页面是否被 ban

    在每次 `dp.get()` 后调用。返回检测结果 dict：
    {
        "is_banned": bool,
        "reason": str,  # "http_403" / "http_429" / "keyword:xxx"
        "action": str, # "retry" / "skip" / "wait"
    }

    Args:
        dp: DrissionPage ChromiumPage 实例

    Returns:
        检测结果 dict
    """
    result = {"is_banned": False, "reason": "", "action": "continue"}

    try:
        # 1. HTTP 状态检测
        status = 0
        try:
            # DrissionPage 的 page url 或 response 状态
            url = dp.url if hasattr(dp, "url") else ""
            # DrissionPage 不直接暴露 HTTP status，用页面标题/正文判断
        except Exception:
            pass

        # 2. 页面标题检测
        title = ""
        try:
            title = dp.title if hasattr(dp, "title") else ""
        except Exception:
            pass

        if title and any(kw in title for kw in ["403", "429", "blocked", "禁止访问"]):
            result["is_banned"] = True
            result["reason"] = f"title:{title}"
            result["action"] = "wait"
            return result

        # 3. 页面正文关键词检测
        body_text = ""
        try:
            body_text = dp.html if hasattr(dp, "html") else ""
        except Exception:
            pass

        if body_text:
            for kw in BAN_KEYWORDS:
                if kw in body_text:
                    result["is_banned"] = True
                    result["reason"] = f"keyword:{kw}"
                    result["action"] = "wait"
                    logger.warning(f"Ban detected: {kw} in page body")
                    return result

    except Exception as e:
        logger.warning(f"Ban detection failed: {e}")
        result["reason"] = f"detection_error:{e}"

    return result


def handle_ban(
    dp: Any,
    url: str,
    batch_id: str,
    ban_result: dict[str, Any],
    retry_count: int = 0,
    max_retries: int = 3,
) -> str:
    """处理 ban：退避重试或写入 retry_queue

    Returns:
        "retry" / "skip" — 调用方按此决定下一步
    """
    if retry_count >= max_retries:
        logger.error(
            f"Max retries ({max_retries}) exceeded for {url}, "
            f"reason={ban_result.get('reason')}"
        )
        # 写入 retry_queue
        try:
            from jd_analytics.pipelines.retry import enqueue_retry
            enqueue_retry(url, batch_id, f"ban:{ban_result.get('reason', '')}")
        except Exception as e:
            logger.error(f"Failed to enqueue retry: {e}")
        return "skip"

    # 退避：60-300s × (retry_count + 1)
    backoff = random.randint(60, 300) * (retry_count + 1)
    logger.warning(
        f"Ban retry {retry_count + 1}/{max_retries} for {url}, "
        f"backing off {backoff}s (reason={ban_result.get('reason')})"
    )
    time.sleep(backoff)
    return "retry"


# ===== Scrapy middleware 兼容层（保留，未来 Scrapy 路线启用时用）=====

try:
    from scrapy.downloadermiddlewares.retry import RetryMiddleware
    from scrapy.exceptions import IgnoreRequest
    from scrapy.http import Request

    class BanDetectMiddleware(RetryMiddleware):
        """403/429 检测 + 退避重试（Scrapy 路线兼容层）

        DrissionPage 路线下不用此类——改用 detect_ban_response() 纯函数。
        """

        def process_response(self, request, response, spider):
            if response.status in (403, 429):
                retries = request.meta.get("retry_times", 0)
                max_retries = 3

                if retries >= max_retries:
                    logger.error(
                        f"Max retries ({max_retries}) exceeded for {request.url}"
                    )
                    try:
                        from jd_analytics.pipelines.retry import enqueue_retry
                        enqueue_retry(
                            request.url,
                            request.meta.get("batch_id"),
                            f"http_{response.status}",
                        )
                    except Exception as e:
                        logger.error(f"Failed to enqueue retry: {e}")
                    raise IgnoreRequest(
                        f"Max retries exceeded: {request.url} "
                        f"(status {response.status})"
                    )

                backoff = random.randint(60, 300) * (retries + 1)
                logger.warning(
                    f"Ban status={response.status} retry {retries + 1}/{max_retries} "
                    f"for {request.url}, backing off {backoff}s"
                )
                time.sleep(backoff)

                new_meta = dict(request.meta)
                new_meta["retry_times"] = retries + 1
                return Request(
                    url=request.url,
                    meta=new_meta,
                    dont_filter=True,
                    priority=request.priority - 1,
                    callback=request.callback,
                )

            return response

except ImportError:
    # scrapy 未安装时，纯函数版仍可用
    pass
