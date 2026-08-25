"""
轻量 UA 轮换中间件（极简版，不用 fake-useragent 库）

参考 JD_Spider 默认 UA + Chrome 主流版本池。
"""
from __future__ import annotations

import random


# Chrome 主流版本（避免太老的版本被识别为爬虫）
CHROME_VERSIONS = [
    "120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0",
    "124.0.0.0", "125.0.0.0", "126.0.0.0", "127.0.0.0",
]

PLATFORMS = ['"Windows"', '"macOS"', '"Linux"']


class FingerprintMiddleware:
    """UA + sec-ch-ua 轻量轮换"""

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request, spider):
        version = random.choice(CHROME_VERSIONS)
        platform = random.choice(PLATFORMS)

        request.headers["User-Agent"] = (
            f"Mozilla/5.0 (compatible; Chrome/{version}) "
            f"Safari/537.36"
        )
        request.headers["sec-ch-ua"] = (
            f'"Not_A Brand";v="8", "Chromium";v="{version.split(".")[0]}", '
            f'"Google Chrome";v="{version.split(".")[0]}"'
        )
        request.headers["sec-ch-ua-mobile"] = "?0"
        request.headers["sec-ch-ua-platform"] = platform

        request.headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        )
        request.headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"
        request.headers["Accept-Encoding"] = "gzip, deflate, br"
        request.headers["Upgrade-Insecure-Requests"] = "1"
