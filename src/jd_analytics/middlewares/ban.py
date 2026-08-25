"""
反爬栈 Layer 4: 检测层 - 403/429 ban 检测（spec §3.5）

连续 403/429 → IP 降权 + 换 IP 重试。
"""
from __future__ import annotations

import logging

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.exceptions import StopDownload
from scrapy.http import Request

logger = logging.getLogger(__name__)


class BanDetectMiddleware(RetryMiddleware):
    """403/429 检测 + 换 IP 重试"""

    def process_response(self, request, response, spider):
        if response.status in (403, 429):
            proxy_obj = request.meta.get("proxy_obj")
            ip = proxy_obj.ip if proxy_obj else "unknown"
            logger.warning(f"Ban detected: status={response.status} IP={ip}")

            if proxy_obj and hasattr(spider, "proxy_pool"):
                spider.proxy_pool.report_failure(proxy_obj.ip, f"http_{response.status}")

            # 换 IP 重试（去掉旧 proxy meta，由 ProxyRotationMiddleware 重新分配）
            new_meta = {k: v for k, v in request.meta.items()
                       if not k.startswith("proxy")}
            new_meta["dont_redirect"] = True
            return Request(
                url=request.url,
                meta=new_meta,
                dont_filter=True,
                priority=request.priority - 1,
            )

        return response
