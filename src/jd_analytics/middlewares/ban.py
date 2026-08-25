"""
403/429 ban 检测中间件（spec §3.5 极简版）

单 IP 模式下被 ban → 写入 retry_queue + 退避重试
"""
from __future__ import annotations

import logging
import random
import time

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Request

logger = logging.getLogger(__name__)


class BanDetectMiddleware(RetryMiddleware):
    """403/429 检测 + 退避重试"""

    def process_response(self, request, response, spider):
        if response.status in (403, 429):
            retries = request.meta.get("retry_times", 0)
            max_retries = 3

            if retries >= max_retries:
                logger.error(
                    f"Max retries ({max_retries}) exceeded for {request.url}"
                )
                # 写入 retry_queue（spec §8.3）
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
                    f"Max retries exceeded: {request.url} (status {response.status})"
                )

            # 退避重试：1h / 6h / 24h 简化版 = 短期 60-300 秒
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
