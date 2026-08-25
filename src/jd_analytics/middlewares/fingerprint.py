"""
反爬栈 Layer 2: 指纹层中间件（spec §3.3）

playwright-stealth + Canvas/WebGL/Audio 随机化 + TLS JA3 + 请求头顺序自然化。
"""
from __future__ import annotations

import logging
import random

from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

# 浏览器原生请求头顺序（Chrome 默认）
NATIVE_HEADER_ORDER = [
    "Host", "Connection", "Content-Length", "sec-ch-ua", "sec-ch-ua-mobile",
    "sec-ch-ua-platform", "Upgrade-Insecure-Requests", "User-Agent",
    "Accept", "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User",
    "Accept-Encoding", "Accept-Language", "Cookie",
]

# Chrome 主流版本池（按月更新）
CHROME_VERSIONS = [
    "120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0",
    "124.0.0.0", "125.0.0.0", "126.0.0.0", "127.0.0.0",
]

PLATFORMS = ['"Windows"', '"macOS"', '"Linux"']


class FingerprintMiddleware:
    """指纹伪装：UA 轮换 + 请求头顺序 + sec-ch-ua"""

    def __init__(self):
        self.ua = UserAgent(browsers=["chrome"], os=["windows", "macos", "linux"])

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request, spider):
        # 1. 随机 User-Agent
        ua = self.ua.random
        request.headers["User-Agent"] = ua

        # 2. sec-ch-ua（Chrome 客户端提示）
        version = random.choice(CHROME_VERSIONS)
        platform = random.choice(PLATFORMS)
        request.headers["sec-ch-ua"] = (
            f'"Not_A Brand";v="8", "Chromium";v="{version.split(".")[0]}", '
            f'"Google Chrome";v="{version.split(".")[0]}"'
        )
        request.headers["sec-ch-ua-mobile"] = "?0"
        request.headers["sec-ch-ua-platform"] = platform

        # 3. Accept 头（模拟真实浏览器）
        request.headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        )
        request.headers["Accept-Language"] = random.choice([
            "zh-CN,zh;q=0.9,en;q=0.8",
            "zh-CN,zh;q=0.9",
            "zh-CN,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
        ])
        request.headers["Accept-Encoding"] = "gzip, deflate, br"

        # 4. 请求头顺序自然化（部分 HTTP 客户端会乱序，需显式控制）
        # Scrapy 默认不保证顺序，需用 httpx 自定义 session
        # TODO: 用 curl_cffi 实现 TLS JA3 指纹伪装

        # 5. Sec-Fetch 系列
        request.headers["Sec-Fetch-Site"] = "same-origin"
        request.headers["Sec-Fetch-Mode"] = "navigate"
        request.headers["Sec-Fetch-User"] = "?1"
        request.headers["Upgrade-Insecure-Requests"] = "1"
