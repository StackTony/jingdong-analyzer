"""
UA 轮换（spec §3.3 + F001-ocr-route P0-1 修复）

DrissionPage 路线下，UA 轮换从 Scrapy 中间件改造为：
- 纯函数 `get_random_ua()` 生成 UA 字符串
- `apply_ua_to_drission(co, ua)` 在 ChromiumOptions 上设置 UA

DrissionPage 用真实 Chrome 浏览器，UA 轮换在 `ChromiumOptions` 层设置
（启动时一次性，不是每个请求轮换——但每次重启浏览器会换）。

保留 FingerprintMiddleware 类兼容 Scrapy 路线。
"""
from __future__ import annotations

import random
from typing import Any


# Chrome 主流版本（避免太老版本被识别为爬虫）
CHROME_VERSIONS = [
    "120.0.0.0", "121.0.0.0", "122.0.0.0", "123.0.0.0",
    "124.0.0.0", "125.0.0.0", "126.0.0.0", "127.0.0.0",
]

PLATFORMS = ['"Windows"', '"macOS"', '"Linux"']


def get_random_ua() -> dict[str, str]:
    """生成一组随机 UA 相关 headers

    Returns:
        dict with keys: user_agent, sec_ch_ua, sec_ch_ua_mobile, sec_ch_ua_platform,
                        accept, accept_language, accept_encoding
    """
    version = random.choice(CHROME_VERSIONS)
    platform = random.choice(PLATFORMS)
    major = version.split(".")[0]

    return {
        "user_agent": (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36"
        ),
        "sec_ch_ua": (
            f'"Not_A Brand";v="8", "Chromium";v="{major}", '
            f'"Google Chrome";v="{major}"'
        ),
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": platform,
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "accept_encoding": "gzip, deflate, br",
    }


def apply_ua_to_drission(co: Any, ua_dict: dict[str, str] | None = None) -> None:
    """在 ChromiumOptions 上设置 UA

    DrissionPage 启动时设置 UA（每个浏览器实例固定一个 UA）。
    若要轮换 UA，需要重启浏览器实例。

    Args:
        co: DrissionPage ChromiumOptions 实例
        ua_dict: UA 字典（None 则随机生成）
    """
    if ua_dict is None:
        ua_dict = get_random_ua()

    # DrissionPage ChromiumOptions 的 UA 设置 API
    # set_user_agent 方法存在于 ChromiumOptions
    try:
        co.set_user_agent(ua_dict["user_agent"])
    except Exception:
        # 某些 DrissionPage 版本用不同 API，降级
        co.set_argument(f"--user-agent={ua_dict['user_agent']}")

    # sec-ch-ua 等通过 headers 设置
    try:
        co.set_pref(
            "sec-ch-ua", ua_dict["sec_ch_ua"]
        )
    except Exception:
        pass  # DrissionPage 可能不支持 sec-ch-ua 覆盖


# ===== Scrapy middleware 兼容层 =====

try:
    class FingerprintMiddleware:
        """UA + sec-ch-ua 轻量轮换（Scrapy 路线兼容层）

        DrissionPage 路线下不用此类——改用 get_random_ua() + apply_ua_to_drission()。
        """

        @classmethod
        def from_crawler(cls, crawler):
            return cls()

        def process_request(self, request, spider):
            ua_dict = get_random_ua()
            request.headers["User-Agent"] = ua_dict["user_agent"]
            request.headers["sec-ch-ua"] = ua_dict["sec_ch_ua"]
            request.headers["sec-ch-ua-mobile"] = ua_dict["sec_ch_ua_mobile"]
            request.headers["sec-ch-ua-platform"] = ua_dict["sec_ch_ua_platform"]
            request.headers["Accept"] = ua_dict["accept"]
            request.headers["Accept-Language"] = ua_dict["accept_language"]
            request.headers["Accept-Encoding"] = ua_dict["accept_encoding"]
            request.headers["Upgrade-Insecure-Requests"] = "1"

except Exception:
    pass
