"""
DrissionPage 京东品类爬虫（spec §3 简化版 - 真实浏览器 + 网络监听）

参考文档：C:\\Users\\23363\\Data\\code\\my-obsidian-wiki\\使用DrissionPage库爬取京东上的商品信息...md

核心原理：
1. 用 DrissionPage 启动真实 Chrome 浏览器
2. 监听 api.m.jd.com/api?appid=search-pc-java&t 接口
3. 拦截 JSON 响应，直接提取 wareName / ori_price / estimatedPrice / totalSales / shopName / skuId
4. 不依赖 HTML 选择器，不依赖评论 API（已被京东封禁），不需要月度 delta 方法

vs scrapy + playwright 方案的优势：
- 真实浏览器行为 → 反爬检测难度高
- 单次 JSON 包含全部字段 → 不用访问 item.jd.com 详情页
- totalSales 字段直出 → spec §2 销量代理可简化（不再依赖评价数差）

用法：
    python -m jd_analytics.spiders.drission_spider --trial
    python -m jd_analytics.spiders.drission_spider --category 棉柔巾 --pages 5
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import yaml
from DrissionPage import ChromiumPage, ChromiumOptions

from jd_analytics.pipelines.dedup import DedupPipeline
from jd_analytics.pipelines.storage import StoragePipeline
from jd_analytics.pipelines.validation import ValidationPipeline
from jd_analytics.pipelines.coldstorage import ColdStoragePipeline
from jd_analytics.settings import (
    CATEGORIES_CONFIG, COMPLIANCE_CONFIG, DAILY_LIMIT_PER_IP,
    COLD_STORAGE_PATH,
)

logger = logging.getLogger(__name__)


# 监听的目标 API（spec §3 - 京东商品列表 JSON 接口）
JD_SEARCH_API_PATTERN = "https://api.m.jd.com/api?appid=search-pc-java&t"

# 搜索 URL 模板（首页搜索结果）
JD_SEARCH_URL = (
    "https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
    "&qrst=1&rt=1&stop=1&vt=2&page={page}&click=0"
)


def is_valid_product(item: dict[str, Any]) -> bool:
    """校验商品字典结构完整（参考掘金文档 §4.2）

    京东 JSON 接口可能混入广告/推荐等非商品字典，需保证必需字段都存在。
    """
    try:
        _ = item["wareName"]
        _ = item["wareBuried"]["ori_price"]
        _ = item["finalPrice"]["estimatedPrice"]
        _ = item["totalSales"]
        _ = item["shopName"]
        _ = item["skuId"]
        return True
    except (KeyError, TypeError, IndexError):
        return False


def clean_title(title: str) -> str:
    """清洗商品标题中的 HTML 标签与换行（参考掘金文档 §4.4）"""
    if not title:
        return ""
    title = title.replace("\n", "")
    return re.sub(r"<.*?>", "", title).strip()


class DrissionSpider:
    """DrissionPage 京东品类爬虫

    铲屎官拍板：单 IP 慢爬，无代理池。
    限速策略：每页间 sleep 3-5 秒 + AutoThrottle-like 自适应。

    重要发现（2026-08-25）：京东已对 search.jd.com/Search 强制登录验证。
    即使真实浏览器访问也会被重定向到 passport.jd.com。
    解决方案：manual_login 模式 — 启动浏览器后人工登录一次，cookies 持久化到
    user_data_path，后续爬取自动复用登录态。
    """

    def __init__(
        self,
        batch_id: str | None = None,
        month: str | None = None,
        trial: bool = False,
        max_pages_per_category: int = 5,
        headless: bool = False,
        page_sleep_seconds: float = 3.0,
        manual_login: bool = False,
        login_wait_seconds: int = 120,
        user_data_path: str | None = None,
    ):
        self.batch_id = batch_id or self._default_batch_id()
        self.month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        self.trial = trial
        self.max_pages_per_category = max_pages_per_category
        self.page_sleep_seconds = page_sleep_seconds
        self.manual_login = manual_login
        self.login_wait_seconds = login_wait_seconds
        self.user_data_path = user_data_path or (
            r"C:\Users\23363\AppData\Local\Temp\drission_chrome_jd_profile"
        )

        # 加载品类配置
        with open(CATEGORIES_CONFIG, encoding="utf-8") as f:
            self.categories_config = yaml.safe_load(f)

        # 加载合规配置
        with open(COMPLIANCE_CONFIG, encoding="utf-8") as f:
            self.compliance = yaml.safe_load(f)

        # Pipelines（直接复用 scrapy pipeline 逻辑）
        self.validation_pipeline = ValidationPipeline()
        self.dedup_pipeline = DedupPipeline()
        self.storage_pipeline = StoragePipeline()
        self.cold_storage_pipeline = ColdStoragePipeline()

        # 单 IP 日请求计数
        self.daily_limit = DAILY_LIMIT_PER_IP
        self.daily_counter = 0

        # 浏览器实例
        self.dp: ChromiumPage | None = None
        self.headless = headless

    @staticmethod
    def _default_batch_id() -> str:
        return datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace(":", "").replace("+", "")

    def _init_browser(self) -> None:
        """启动 Chrome 浏览器实例"""
        co = ChromiumOptions()
        if self.headless:
            co.headless()
        co.set_argument("--disable-blink-features=AutomationControlled")
        # 持久化 user_data 让登录态保留
        co.set_user_data_path(self.user_data_path)
        co.set_argument("--profile-directory=Default")
        self.dp = ChromiumPage(co)
        logger.info(
            f"Browser started, headless={self.headless}, "
            f"user_data={self.user_data_path}"
        )

        if self.manual_login:
            self._do_manual_login()

    def _do_manual_login(self) -> None:
        """打开浏览器让用户手动登录，登录态保存到 user_data_path"""
        assert self.dp is not None
        logger.warning("=" * 60)
        logger.warning("MANUAL LOGIN MODE")
        logger.warning(
            f"请在打开的浏览器窗口中手动登录京东账号，登录后等待 {self.login_wait_seconds}s"
        )
        logger.warning("登录态会保存到 user_data_path，下次复用无需再登录")
        logger.warning("=" * 60)

        # 访问登录页
        self.dp.get("https://passport.jd.com/new/login.aspx")
        # 等待用户登录
        time.sleep(self.login_wait_seconds)

        # 检测登录成功
        cookies = self.dp.cookies()
        cookie_names = [c.get("name", "") for c in cookies]
        if "pin" in cookie_names or "pt_key" in cookie_names or "pt_pin" in cookie_names:
            logger.info("Login detected (pin/pt_key/pt_pin cookie present)")
        else:
            logger.warning(
                "Login cookie not detected. Will attempt to continue anyway."
            )
            logger.warning(f"Cookie names: {cookie_names[:15]}")

    def _close_browser(self) -> None:
        if self.dp:
            try:
                self.dp.quit()
            except Exception as e:
                logger.warning(f"Browser close failed: {e}")
            self.dp = None

    def _check_daily_limit(self) -> bool:
        """单 IP 日配额检查（spec §3.7）"""
        if self.daily_counter >= self.daily_limit:
            logger.error(
                f"Daily limit {self.daily_limit} reached, aborting batch"
            )
            return False
        return True

    def crawl_category(self, category: dict[str, Any]) -> list[dict[str, Any]]:
        """爬取单个品类的商品列表

        流程：
        1. 构造搜索 URL（page=1）
        2. 启动网络监听
        3. 访问页面 → 滚动加载 → 拦截 JSON
        4. 点击"下一页" → 重复
        """
        name = category["name"]
        keyword = (category.get("aliases") or [name])[0]
        cid2 = category.get("cid2", "")
        cid3 = category.get("cid3", "")
        logger.info(
            f"=== 开始爬品类 {name} (keyword={keyword}, cid2={cid2}, cid3={cid3}) ==="
        )

        # 启动浏览器监听
        assert self.dp is not None, "Browser not initialized"
        self.dp.listen.start(JD_SEARCH_API_PATTERN)

        all_items: list[dict[str, Any]] = []
        page = 1
        while page <= self.max_pages_per_category:
            if not self._check_daily_limit():
                break

            logger.info(f"[{name}] page {page}/{self.max_pages_per_category}")
            page_items = self._crawl_single_page(name, keyword, page)
            all_items.extend(page_items)
            logger.info(
                f"[{name}] page {page} done: +{len(page_items)} items "
                f"(total {len(all_items)})"
            )

            if page >= self.max_pages_per_category:
                break

            # 点击"下一页" + 限速
            if not self._click_next_page():
                logger.info(f"No more pages for {name}")
                break

            page += 1
            # 单 IP 慢爬防封：每页间 sleep
            sleep_sec = self.page_sleep_seconds + (page % 2)  # 3-4 秒
            logger.debug(f"Sleeping {sleep_sec}s between pages")
            time.sleep(sleep_sec)

        self.dp.listen.stop()
        logger.info(f"=== 品类 {name} finished: {len(all_items)} items ===")
        return all_items

    def _crawl_single_page(
        self, category_name: str, keyword: str, page: int
    ) -> list[dict[str, Any]]:
        """爬取单页：访问 → 滚动 → 拦截 JSON → 解析商品"""
        assert self.dp is not None

        # 1. 访问搜索页
        url = JD_SEARCH_URL.format(keyword=quote(keyword), page=page)
        if page == 1:
            self.dp.get(url)
        # 后续页通过点击下一页触发，不再重新 get
        self.daily_counter += 1

        # 2. 滚动到页底加载懒加载内容
        try:
            next_btn = self.dp.ele("text=下一页", timeout=2)
            if next_btn:
                self.dp.scroll.to_see(next_btn)
        except Exception:
            # 末页可能没有"下一页"按钮
            self.dp.scroll.to_bottom()

        # 3. 等待并拦截 JSON 响应
        # 掘金文档：监听 5 个数据包，过滤出 abBuriedTagMap 字典
        try:
            resp_list = self.dp.listen.wait(5, timeout=15)
        except Exception as e:
            logger.warning(f"Listen wait failed on page {page}: {e}")
            return []

        if not resp_list:
            logger.warning(f"No responses captured on page {page}")
            return []

        page_items: list[dict[str, Any]] = []
        for resp in resp_list:
            try:
                json_data = resp.response.body
                if not isinstance(json_data, dict):
                    continue
                if "abBuriedTagMap" not in json_data:
                    continue

                ware_list = json_data.get("data", {}).get("wareList", [])
                for ware in ware_list:
                    if not is_valid_product(ware):
                        continue

                    item = self._build_item(ware, category_name, keyword, page)
                    page_items.append(item)
            except Exception as e:
                logger.warning(f"Failed to parse resp: {e}")
                continue

        # 4. 通过 pipeline 链处理
        processed: list[dict[str, Any]] = []
        for item in page_items:
            try:
                # ValidationPipeline
                item = self.validation_pipeline.process_item(item, spider=None)
                # DedupPipeline
                item = self.dedup_pipeline.process_item(item, spider=None)
                # StoragePipeline (入主库)
                self.storage_pipeline.process_item(item, spider=None)
                # ColdStoragePipeline（保存原始 JSON 作 debug）
                item["raw_html"] = json.dumps(
                    item, ensure_ascii=False
                )  # 复用 raw_html 字段冷存
                self.cold_storage_pipeline.process_item(item, spider=None)
                processed.append(item)
            except Exception as e:
                # DropItem 等异常不中断
                logger.debug(f"Pipeline dropped item: {e}")

        return processed

    def _build_item(
        self, ware: dict[str, Any], category_name: str, keyword: str, page: int
    ) -> dict[str, Any]:
        """从 JSON 商品字典构造 pipeline item"""
        title = clean_title(ware.get("wareName", ""))
        ori_price = ware.get("wareBuried", {}).get("ori_price")
        final_price = ware.get("finalPrice", {}).get("estimatedPrice")
        total_sales = ware.get("totalSales", 0)
        shop_name = ware.get("shopName", "")
        sku_id = str(ware.get("skuId", ""))

        # spec §2 简化版：totalSales 直出，不再用评价数差代理
        return {
            "spu_id": sku_id,  # 京东搜索接口 skuId 即 SPU ID（试爬简化）
            "batch_id": self.batch_id,
            "month": self.month,
            "category": category_name,
            "keyword": keyword,
            "title": title,
            "brand_name_raw": shop_name,  # 京东接口里 shopName 通常包含品牌信息
            "url": f"https://item.jd.com/{sku_id}.html",
            "page": page,
            # 价格字段（spec §4.1 - sku_detail）
            "price": float(final_price) if final_price else None,
            "ori_price": float(ori_price) if ori_price else None,
            # spec §2 简化版：销量直接来自 totalSales
            "cumu_review_count": int(total_sales),  # 字段名沿用，语义变为"销量"
            "total_sales": int(total_sales),
            # 评论字段（不再抓，留空）
            "good_count": 0,
            "general_count": 0,
            "poor_count": 0,
            "show_count": 0,
        }

    def _click_next_page(self) -> bool:
        """点击"下一页"按钮翻页"""
        assert self.dp is not None
        try:
            next_btn = self.dp.ele("text=下一页", timeout=2)
            if next_btn:
                next_btn.click()
                self.dp.wait(1)
                return True
        except Exception as e:
            logger.debug(f"Click next page failed: {e}")
        return False

    def run(self) -> dict[str, int]:
        """执行爬取

        trial 模式：只跑 trial_category（手机品类验证管道）
        正式模式：跑所有有 cid2/cid3 的品类
        """
        self._init_browser()
        try:
            results: dict[str, int] = {}

            if self.trial and self.categories_config.get("trial_category"):
                cat = self.categories_config["trial_category"]
                logger.warning(
                    f"TRIAL MODE: using {cat['name']} cid2={cat.get('cid2')} "
                    f"cid3={cat.get('cid3')} (max_pages={self.max_pages_per_category})"
                )
                items = self.crawl_category(cat)
                results[cat["name"]] = len(items)
            else:
                for cat in self.categories_config.get("categories", []):
                    if not cat.get("cid2") or not cat.get("cid3"):
                        logger.info(
                            f"Skipping {cat['name']}: no cid2/cid3 configured"
                        )
                        continue
                    items = self.crawl_category(cat)
                    results[cat["name"]] = len(items)

            logger.info(f"=== All done: {results} ===")
            return results
        finally:
            self._close_browser()


def main():
    parser = argparse.ArgumentParser(description="DrissionPage 京东品类爬虫")
    parser.add_argument("--batch-id", help="批次 ID（默认 UTC 时间戳）")
    parser.add_argument("--month", help="YYYY-MM，默认本月")
    parser.add_argument(
        "--trial", action="store_true", help="试爬模式（1 品类 × max_pages 页）"
    )
    parser.add_argument(
        "--category", help="只跑指定品类名（如 棉柔巾·绵柔巾）"
    )
    parser.add_argument(
        "--max-pages", type=int, default=2,
        help="每个品类最大爬取页数（试爬默认 2 页 = 约 120 商品）",
    )
    parser.add_argument(
        "--headless", action="store_true", help="无头模式（默认可见浏览器）"
    )
    parser.add_argument(
        "--page-sleep", type=float, default=3.0,
        help="每页之间 sleep 秒数（默认 3.0，单 IP 慢爬防封）",
    )
    parser.add_argument(
        "--manual-login", action="store_true",
        help="启动浏览器后人工登录京东账号（cookies 持久化到 user_data_path）",
    )
    parser.add_argument(
        "--login-wait", type=int, default=120,
        help="人工登录等待秒数（默认 120s，仅 --manual-login 时生效）",
    )
    parser.add_argument(
        "--user-data-path",
        default=r"C:\Users\23363\AppData\Local\Temp\drission_chrome_jd_profile",
        help="Chrome 用户数据目录（保存登录态）",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    spider = DrissionSpider(
        batch_id=args.batch_id,
        month=args.month,
        trial=args.trial,
        max_pages_per_category=args.max_pages,
        headless=args.headless,
        page_sleep_seconds=args.page_sleep,
        manual_login=args.manual_login,
        login_wait_seconds=args.login_wait,
        user_data_path=args.user_data_path,
    )

    # 初始化数据库（建表）
    from sqlalchemy import create_engine
    from jd_analytics.models import Base, Batch
    from jd_analytics.settings import DATABASE_URL

    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    stmt = sqlite_insert(Batch).values(
        batch_id=spider.batch_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        month=spider.month,
        is_remediation=False,
    ).on_conflict_do_nothing(index_elements=["batch_id"])
    with engine.begin() as conn:
        conn.execute(stmt)

    # 跑爬虫
    results = spider.run()

    # 抓取完 → 聚合 Top30（spec §6.3）
    try:
        from jd_analytics.aggregator import aggregate_top30
        aggregate_top30(spider.batch_id, spider.month)
    except Exception as e:
        logger.error(f"Aggregator failed: {e}")

    # 生成报告
    try:
        from jd_analytics.batch_report import generate_batch_report
        path = generate_batch_report(spider.batch_id)
        print(f"Report: {path}")
    except Exception as e:
        logger.error(f"Batch report failed: {e}")

    print(f"Done. batch_id={spider.batch_id}, results={results}")


if __name__ == "__main__":
    main()
