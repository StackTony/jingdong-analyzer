"""
京东品类 Spider（参考 JD_Spider 极简实现）

三级 URL：
1. search.jd.com/Search         → 列表页前 30 商品
2. search.jd.com/s_new.php       → 列表页后 30 商品（异步加载）
3. club.jd.com/comment/...       → 评论数 JSON API（直出 CommentCount）

之后访问 item.jd.com/{spu_id}.html 抓品牌/标题。

参考：C:\\Users\\23363\\Data\\code\\JD_Spider\\spiders\\jd_phone.py
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

import yaml
from scrapy import Spider, Request
from scrapy.http import Response

from jd_analytics.settings import (
    JD_SEARCH_URL, JD_SEARCH_ASYNC_URL, JD_COMMENT_API, JD_ITEM_URL,
    CATEGORIES_CONFIG, MAX_PAGES_PER_CATEGORY, COMPLIANCE_CONFIG,
)

logger = logging.getLogger(__name__)


class JdCategorySpider(Spider):
    """京东品类 Spider - 参考 JD_Spider 极简实现

    铲屎官拍板：单 IP 慢爬模式，无代理池。
    """

    name = "jd_category"
    allowed_domains = ["jd.com", "search.jd.com", "item.jd.com", "club.jd.com"]

    def __init__(self, batch_id: str | None = None, month: str | None = None,
                 trial: bool = False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_id = batch_id
        self.month = month
        self.trial = trial

        # 加载品类配置
        with open(CATEGORIES_CONFIG, encoding="utf-8") as f:
            self.categories_config = yaml.safe_load(f)

        # 加载合规配置（spec §1.3）
        with open(COMPLIANCE_CONFIG, encoding="utf-8") as f:
            self.compliance = yaml.safe_load(f)

        # 试爬模式：只跑 1 个品类 × 2 页（约 120 商品）
        if self.trial:
            self.trial_pages = 2
            logger.warning(
                f"TRIAL MODE: trial_pages={self.trial_pages} (1 category × 2 pages)"
            )

    async def start(self):
        """对每个品类发起第一页请求（Scrapy 2.13+ 用 async start）"""
        # 试爬模式：用 JD_Spider 验证过的手机品类（cid2=653 cid3=655）
        if self.trial and self.categories_config.get("trial_category"):
            cat = self.categories_config["trial_category"]
            logger.warning(
                f"TRIAL MODE: using {cat['name']} cid2={cat['cid2']} cid3={cat['cid3']}"
            )
            keyword = cat["aliases"][0]
            url = JD_SEARCH_URL.format(
                keyword=quote(keyword),
                cid2=cat["cid2"],
                cid3=cat["cid3"],
                page=1,
            )
            self.logger.info(f"Start URL: {url}")
            yield Request(
                url=url,
                callback=self.parse_list,
                meta={
                    "batch_id": self.batch_id,
                    "category": cat["name"],
                    "keyword": keyword,
                    "cid2": cat["cid2"],
                    "cid3": cat["cid3"],
                    "page": 1,
                },
                dont_filter=True,
            )
            return

        # 正式模式：跑 11 品类
        for cat in self.categories_config["categories"]:
            # 跳过未确认 cid 的品类
            if not cat.get("cid2") or not cat.get("cid3"):
                logger.info(f"Skipping {cat['name']}: no cid2/cid3 configured")
                continue

            keyword = cat["aliases"][0] if cat.get("aliases") else cat["name"]
            url = JD_SEARCH_URL.format(
                keyword=quote(keyword),
                cid2=cat["cid2"],
                cid3=cat["cid3"],
                page=1,
            )
            self.logger.info(f"Start URL: {url}")
            yield Request(
                url=url,
                callback=self.parse_list,
                meta={
                    "batch_id": self.batch_id,
                    "category": cat["name"],
                    "keyword": keyword,
                    "cid2": cat["cid2"],
                    "cid3": cat["cid3"],
                    "page": 1,
                },
                dont_filter=True,
            )

    def parse_list(self, response: Response):
        """解析列表页前 30 商品"""
        category = response.meta["category"]
        keyword = response.meta["keyword"]
        cid2 = response.meta["cid2"]
        cid3 = response.meta["cid3"]
        page = response.meta["page"]

        # 收集前 30 商品 ID
        id_list = []
        gl_items = response.css(".gl-item")
        logger.info(f"[{category}] page {page} (前30): {len(gl_items)} items")

        for gl_item in gl_items:
            spu_id = gl_item.css(".gl-item::attr(data-pid)").get()
            if not spu_id:
                continue

            price_text = gl_item.css(".gl-i-wrap .p-price strong i::text").get()
            price = self._parse_price(price_text)
            url = gl_item.css(".gl-i-wrap .p-name a::attr(href)").get("")
            if url.startswith("//"):
                url = "https:" + url

            id_list.append(spu_id)

            # 请求评论 JSON API
            yield Request(
                url=JD_COMMENT_API.format(spu_id=spu_id),
                callback=self.parse_comment,
                meta={
                    "batch_id": self.batch_id,
                    "category": category,
                    "spu_id": spu_id,
                    "price": price,
                    "item_url": url,
                    "page": page,
                },
                dont_filter=True,
            )

        # 试爬模式：只跑 trial_pages 页
        if self.trial and page >= getattr(self, "trial_pages", 2):
            logger.info(f"TRIAL: stopping at page {page} for {category}")
            return

        # 请求后 30 商品（异步加载，spec §5 - JD_Spider 论证可行）
        if id_list and page < MAX_PAGES_PER_CATEGORY:
            next_page = page + 1
            show_items = ",".join(id_list)
            async_url = JD_SEARCH_ASYNC_URL.format(
                keyword=quote(keyword),
                cid2=cid2,
                cid3=cid3,
                page=next_page,
                show_items=show_items,
            )
            yield Request(
                url=async_url,
                callback=self.parse_list_async,
                meta={
                    "batch_id": self.batch_id,
                    "category": category,
                    "keyword": keyword,
                    "cid2": cid2,
                    "cid3": cid3,
                    "page": next_page,
                    "referer": response.url,
                },
                headers={"Referer": response.url},
            )

    def parse_list_async(self, response: Response):
        """解析列表页后 30 商品（异步加载）"""
        category = response.meta["category"]
        keyword = response.meta["keyword"]
        cid2 = response.meta["cid2"]
        cid3 = response.meta["cid3"]
        page = response.meta["page"]

        gl_items = response.css(".gl-item")
        logger.info(f"[{category}] page {page} (后30): {len(gl_items)} items")

        for gl_item in gl_items:
            spu_id = gl_item.css(".gl-item::attr(data-pid)").get()
            if not spu_id:
                continue

            price_text = gl_item.css(".gl-i-wrap .p-price strong i::text").get()
            price = self._parse_price(price_text)
            url = gl_item.css(".gl-i-wrap .p-name a::attr(href)").get("")
            if url.startswith("//"):
                url = "https:" + url

            yield Request(
                url=JD_COMMENT_API.format(spu_id=spu_id),
                callback=self.parse_comment,
                meta={
                    "batch_id": self.batch_id,
                    "category": category,
                    "spu_id": spu_id,
                    "price": price,
                    "item_url": url,
                    "page": page,
                },
                dont_filter=True,
            )

        # 试爬模式：达到 trial_pages 停止
        if self.trial and page >= getattr(self, "trial_pages", 2):
            logger.info(f"TRIAL: stopping at page {page} for {category}")
            return

        # 请求下一页（前 30）
        if page < MAX_PAGES_PER_CATEGORY:
            next_url = JD_SEARCH_URL.format(
                keyword=quote(keyword),
                cid2=cid2,
                cid3=cid3,
                page=page + 1,
            )
            yield Request(
                url=next_url,
                callback=self.parse_list,
                meta={
                    "batch_id": self.batch_id,
                    "category": category,
                    "keyword": keyword,
                    "cid2": cid2,
                    "cid3": cid3,
                    "page": page + 1,
                },
            )

    def parse_comment(self, response: Response):
        """解析评论数 JSON API"""
        try:
            data = json.loads(response.text)
            comment_dict = data["CommentsCount"][0]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(
                f"Comment API parse error for {response.meta['spu_id']}: {e}"
            )
            return

        spu_id = response.meta["spu_id"]
        cumu_review_count = comment_dict.get("CommentCount", 0)
        good_count = comment_dict.get("GoodCount", 0)
        general_count = comment_dict.get("GeneralCount", 0)
        poor_count = comment_dict.get("PoorCount", 0)
        show_count = comment_dict.get("ShowCount", 0)

        # 请求详情页拿品牌/标题
        yield Request(
            url=JD_ITEM_URL.format(spu_id=spu_id),
            callback=self.parse_detail,
            meta={
                **response.meta,
                "cumu_review_count": cumu_review_count,
                "good_count": good_count,
                "general_count": general_count,
                "poor_count": poor_count,
                "show_count": show_count,
            },
            dont_filter=True,
        )

    def parse_detail(self, response: Response):
        """解析商品详情页 - 提取品牌/标题"""
        spu_id = response.meta["spu_id"]

        # 京东商品页 brand 选择器（参考 JD_Spider）
        brand = (
            response.css(".inner.border .head a::text").get()
            or response.css("#parameter-brand li::attr(title)").get()
            or ""
        )
        title = (
            response.css("#spec-img::attr(alt)").get()
            or response.css(".sku-name::text").get("")
        ).strip()

        if not brand or not title:
            logger.warning(
                f"Missing brand/title for {spu_id}: brand={brand!r} title={title!r}"
            )
            self._report_selector_failure(response.url, spu_id)

        # PII 脱敏：不抓评论用户昵称/头像/ID（spec §1.4）
        # 评论 API 不返回 PII，无脱敏工作

        item = {
            "spu_id": spu_id,
            "batch_id": self.batch_id,
            "category": response.meta["category"],
            "title": title,
            "brand_name_raw": brand,
            "cumu_review_count": response.meta["cumu_review_count"],
            "good_count": response.meta["good_count"],
            "general_count": response.meta["general_count"],
            "poor_count": response.meta["poor_count"],
            "show_count": response.meta["show_count"],
            "price": response.meta["price"],
            "url": response.url,
            "raw_html": response.text,  # 冷存 debug（spec §4.3）
        }

        yield item

    @staticmethod
    def _parse_price(text: str | None) -> float | None:
        if not text:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)", text)
        return float(m.group(1)) if m else None

    def _report_selector_failure(self, url: str, spu_id: str) -> None:
        """选择器失效告警（spec §12.3）"""
        from datetime import datetime, timezone
        from sqlalchemy import create_engine
        from jd_analytics.models import AnomalyAlert
        from jd_analytics.settings import DATABASE_URL

        try:
            engine = create_engine(DATABASE_URL)
            with engine.begin() as conn:
                conn.execute(
                    AnomalyAlert.__table__.insert().values(
                        batch_id=self.batch_id,
                        alert_type="selector_failure",
                        severity="warning",
                        description=f"Selector v1 failed on {url} (spu={spu_id})",
                        detected_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
        except Exception as e:
            logger.error(f"Failed to record selector failure: {e}")
