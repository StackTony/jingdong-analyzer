"""
京东商品详情页 Spider（spec §4 + §11）

抓取商品标题/品牌/累计评价数/单价/SPU/SKU 等。
按 spec §11 试爬范围：1-2 品类 × 1000 URL。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml
from scrapy import Spider, Request
from scrapy.http import Response

from jd_analytics.settings import COMPLIANCE_CONFIG

logger = logging.getLogger(__name__)


class JdItemSpider(Spider):
    """京东商品详情页 spider"""

    name = "jd_item"
    use_proxy = True

    # 试爬范围（spec §11.2）
    # 正式上线时改成 11 品类全量
    trial_categories = ["婴童纸尿裤", "棉柔巾·绵柔巾"]
    trial_url_per_category = 1000

    def __init__(self, batch_id: str | None = None, month: str | None = None,
                 trial: bool = True, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_id = batch_id
        self.month = month
        self.trial = trial

        # 加载合规配置（spec §1.3）
        with open(COMPLIANCE_CONFIG, encoding="utf-8") as f:
            self.compliance = yaml.safe_load(f)

        # 加载选择器 v1（spec §12）
        selectors_path = Path(__file__).parent.parent / "config" / "selectors" / "v1.yaml"
        with open(selectors_path, encoding="utf-8") as f:
            self.selectors = yaml.safe_load(f)["selectors"]

    def start_requests(self):
        """从 spu_master 表加载待抓 SPU URL"""
        from jd_analytics.models import SpuMaster
        from sqlalchemy import create_engine, select
        from jd_analytics.settings import DATABASE_URL

        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            stmt = select(SpuMaster.spu_id).where(SpuMaster.is_active == True)  # noqa: E712
            if self.trial:
                stmt = stmt.where(
                    SpuMaster.category.in_(self.trial_categories)
                ).limit(self.trial_url_per_category * len(self.trial_categories))

            for (spu_id,) in conn.execute(stmt):
                url = f"https://item.jd.com/{spu_id}.html"
                yield Request(
                    url=url,
                    callback=self.parse_item,
                    meta={
                        "spu_id": spu_id,
                        "batch_id": self.batch_id,
                        "playwright": self._needs_js(),
                        "playwright_page_methods": [],
                    },
                )

    def parse_item(self, response: Response):
        """解析商品详情页"""
        selectors = self.selectors["item_page"]
        try:
            item = {
                "spu_id": response.meta["spu_id"],
                "batch_id": response.meta["batch_id"],
                "title": response.css(selectors["title"]).get(),
                "brand_name_raw": response.css(selectors["brand"]).get(),
                "cumu_review_count": self._parse_review_count(
                    response.css(selectors["cumu_review_count"]).get()
                ),
                "price": self._parse_price(response.css(selectors["price"]).get()),
                "url": response.url,
                "fetched_at": response.meta.get("download_latency"),
            }

            if not item["title"] or not item["brand_name_raw"]:
                # 选择器失效 → 写入 retry_queue + 告警（spec §12.3）
                logger.error(f"Selector failure on {response.url}")
                self._report_selector_failure(response.url)
                return

            yield item

        except Exception as e:
            logger.error(f"Parse error on {response.url}: {e}")
            from jd_analytics.pipelines.retry import enqueue_retry
            enqueue_retry(response.url, self.batch_id, f"parse_error: {e}")

    @staticmethod
    def _needs_js() -> bool:
        """商品详情页大部分服务端渲染，30% 需要 Playwright（spec §3.8 校准项）"""
        import random
        return random.random() < 0.3

    @staticmethod
    def _parse_review_count(text: str | None) -> int | None:
        """'已有 300000 人评价' → 300000"""
        if not text:
            return None
        import re
        m = re.search(r"(\d+)", text.replace(",", ""))
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_price(text: str | None) -> float | None:
        """'￥99.00' → 99.0"""
        if not text:
            return None
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", text)
        return float(m.group(1)) if m else None

    def _report_selector_failure(self, url: str) -> None:
        """选择器失效告警（spec §12.3 改版切换）"""
        from jd_analytics.models import AnomalyAlert
        from sqlalchemy import create_engine
        from jd_analytics.settings import DATABASE_URL
        from datetime import datetime, timezone

        engine = create_engine(DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(
                AnomalyAlert.__table__.insert().values(
                    batch_id=self.batch_id,
                    alert_type="selector_failure",
                    severity="critical",
                    description=f"Selector v1 failed on {url}",
                    detected_at=datetime.now(timezone.utc).isoformat(),
                )
            )
