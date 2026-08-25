"""
反爬栈 Layer 1: 网络层 - 代理池中间件（spec §3.2）

多服务商轮换 + IP 健康检查 + 评分 + 地域分散。
"""
from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProxyHealth:
    """IP 健康状态"""
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_success: float | None = None
    last_failure: float | None = None
    avg_latency: float = 0.0
    is_dead: bool = False
    dead_since: float | None = None

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def score(self) -> float:
        """综合评分：0.5*success + 0.3*(1/latency) + 0.2*(1-ban_count)"""
        latency_score = (1.0 / max(self.avg_latency, 0.1)) if self.avg_latency > 0 else 0
        ban_score = 1.0 - min(self.failure_count / 100, 1.0)
        return 0.5 * self.success_rate + 0.3 * min(latency_score, 1.0) + 0.2 * ban_score


@dataclass
class Proxy:
    """单条代理 IP"""
    ip: str
    port: int
    provider: str
    region: str | None = None
    asn: str | None = None
    health: ProxyHealth = field(default_factory=ProxyHealth)


class ProxyPool:
    """代理池：多服务商轮换 + 健康检查 + 评分"""

    def __init__(self, config_path: str):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.providers = self.config["providers"]
        self.scoring = self.config.get("scoring", {})
        self.geo = self.config.get("geo_distribution", {})
        self.proxies: dict[str, Proxy] = {}
        self._last_health_check: float = 0

    def get(self) -> Proxy:
        """获取评分最高的可用代理"""
        self._maybe_revive_dead()
        available = [p for p in self.proxies.values() if not p.health.is_dead]
        if not available:
            self._refresh_pool()
            available = list(self.proxies.values())

        # 地域分散：避免同 ASN 集中
        if self.geo.get("avoid_same_asn"):
            available = self._diversify_asn(available)

        # 评分排序 + 90% 高分 + 10% 随机（避免可预测性）
        available.sort(key=lambda p: -p.health.score)
        if random.random() < 0.9:
            return available[0]
        return random.choice(available[:min(10, len(available))])

    def report_success(self, ip: str, latency: float) -> None:
        if ip not in self.proxies:
            return
        h = self.proxies[ip].health
        h.success_count += 1
        h.consecutive_failures = 0
        h.last_success = time.time()
        # 指数移动平均
        h.avg_latency = 0.7 * h.avg_latency + 0.3 * latency if h.avg_latency else latency

    def report_failure(self, ip: str, reason: str) -> None:
        if ip not in self.proxies:
            return
        h = self.proxies[ip].health
        h.failure_count += 1
        h.consecutive_failures += 1
        h.last_failure = time.time()
        logger.warning(f"Proxy failure: {ip} reason={reason} consec={h.consecutive_failures}")

        dead_threshold = self.scoring.get("dead_threshold", 3)
        if h.consecutive_failures >= dead_threshold:
            h.is_dead = True
            h.dead_since = time.time()
            logger.warning(f"Proxy dead: {ip} after {h.consecutive_failures} consecutive failures")

    def _maybe_revive_dead(self) -> None:
        """复活超过 revive_after 的死 IP"""
        revive_after_str = self.scoring.get("revive_after", "24h")
        revive_after = self._parse_duration(revive_after_str)
        now = time.time()
        for p in self.proxies.values():
            if p.health.is_dead and p.health.dead_since:
                if now - p.health.dead_since > revive_after:
                    p.health.is_dead = False
                    p.health.dead_since = None
                    p.health.consecutive_failures = 0
                    logger.info(f"Proxy revived: {p.ip}")

    def _diversify_asn(self, proxies: list[Proxy]) -> list[Proxy]:
        """避免同 ASN 集中：每个 ASN 最多取 2 个"""
        by_asn: dict[str, list[Proxy]] = defaultdict(list)
        for p in proxies:
            if p.asn:
                by_asn[p.asn].append(p)
            else:
                by_asn["unknown"].append(p)
        result = []
        for asn, ps in by_asn.items():
            ps.sort(key=lambda x: -x.health.score)
            result.extend(ps[:2])
        return result

    def _refresh_pool(self) -> None:
        """从服务商 API 拉取新 IP"""
        for provider in self.providers:
            try:
                new_ips = self._fetch_from_provider(provider)
                for ip, port, region, asn in new_ips:
                    key = f"{ip}:{port}"
                    if key not in self.proxies:
                        self.proxies[key] = Proxy(
                            ip=ip, port=port, provider=provider["name"],
                            region=region, asn=asn
                        )
            except Exception as e:
                logger.error(f"Failed to fetch from {provider['name']}: {e}")

    def _fetch_from_provider(self, provider: dict) -> list[tuple]:
        """从服务商 API 拉取代理列表（stub：实现需对接具体服务商 SDK）"""
        # TODO: 对接快代理/芝麻代理 SDK
        logger.info(f"Fetching proxies from {provider['name']} (stub)")
        return []

    @staticmethod
    def _parse_duration(s: str) -> float:
        """'24h' → 86400.0, '1h' → 3600.0"""
        unit = s[-1]
        val = float(s[:-1])
        if unit == "h":
            return val * 3600
        if unit == "m":
            return val * 60
        if unit == "s":
            return val
        return val


class ProxyRotationMiddleware:
    """Scrapy 中间件：每个请求绑定代理"""

    def __init__(self, proxy_pool: ProxyPool):
        self.proxy_pool = proxy_pool

    @classmethod
    def from_crawler(cls, crawler):
        from jd_analytics.settings import PROVIDERS_CONFIG
        pool = ProxyPool(PROVIDERS_CONFIG)
        return cls(pool)

    def process_request(self, request, spider):
        if not getattr(spider, "use_proxy", True):
            return
        proxy = self.proxy_pool.get()
        request.meta["proxy"] = f"http://{proxy.ip}:{proxy.port}"
        request.meta["proxy_obj"] = proxy
        spider.proxy_pool = self.proxy_pool  # 供其他中间件用

    def process_response(self, request, response, spider):
        proxy_obj = request.meta.get("proxy_obj")
        if proxy_obj:
            latency = response.meta.get("download_latency", 1.0)
            if response.status == 200:
                self.proxy_pool.report_success(proxy_obj.ip, latency)
            else:
                self.proxy_pool.report_failure(proxy_obj.ip, f"http_{response.status}")
        return response
