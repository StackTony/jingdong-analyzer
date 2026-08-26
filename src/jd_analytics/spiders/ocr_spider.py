"""
OCR 路线京东品类爬虫（spec F001-ocr-route）

核心思路：
- 复用 DrissionSpider 的登录态 + 反爬栈（五层防御全保留）
- 数据提取层从"监听 JSON 接口"换成"整页截图 + PaddleOCR-VL 提取"
- 截图保存 7 天后自动删除
- 本期不实际爬取测试，代码实现完 → @云长 review 反爬是否到位

数据流：
    登录态（复用 DrissionSpider）
        ↓
    访问搜索页（复用）
        ↓
    滚动加载（复用）
        ↓
    整页截图 → 保存 PNG（7天GC）
        ↓
    PaddleOCR-VL 提取文字
        ↓
    按区域规则结构化（商品卡片 → 逐卡片解析字段）
        ↓
    ValidationPipeline → DedupPipeline → StoragePipeline

用法：
    python -m jd_analytics.spiders.ocr_spider --trial
    python -m jd_analytics.spiders.ocr_spider --category 棉柔巾 --pages 5

注意：本期不实际爬取，--dry-run 模式只验证代码路径不访问京东
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from jd_analytics.pipelines.dedup import DedupPipeline
from jd_analytics.pipelines.storage import StoragePipeline
from jd_analytics.pipelines.validation import ValidationPipeline
from jd_analytics.settings import (
    CATEGORIES_CONFIG,
    COMPLIANCE_CONFIG,
    DAILY_LIMIT_PER_IP,
    SCREENSHOT_PATH,
    SCREENSHOT_RETENTION_DAYS,
    OCR_CONFIG_PATH,
)
from jd_analytics.spiders.drission_spider import DrissionSpider, JD_SEARCH_URL
from jd_analytics.utils.screenshot_gc import ScreenshotGC

logger = logging.getLogger(__name__)


class OcrSpider(DrissionSpider):
    """OCR 路线 spider - 继承 DrissionSpider 复用反爬栈

    重写点：
    - `_crawl_single_page`: 改为截图 + OCR 提取
    - 新增 `_take_screenshot`: 整页截图保存
    - 新增 `_run_ocr`: 调用 PaddleOCR-VL 提取文字（lazy import 避免硬依赖）
    - 截图前调用 ScreenshotGC 清理 7 天前文件

    保留点（反爬栈五层防御全保留）：
    - 登录态（auto_login / manual_login / _check_login_state）
    - 限速（page_sleep_seconds + 随机抖动 + 5% 长停留）
    - 单 IP 日配额（_check_daily_limit）
    - UA 轮换（middlewares/fingerprint.py）
    - ban/captcha 检测（middlewares/ban.py / captcha.py）
    """

    def __init__(
        self,
        *args,
        ocr_engine: str = "paddleocr_vl",
        screenshot_format: str = "png",
        dry_run: bool = False,
        screenshot_only: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # OCR 配置
        self.ocr_engine = ocr_engine
        self.screenshot_format = screenshot_format
        self.dry_run = dry_run
        # screenshot_only 模式：截图后不跑 OCR（用于验证截图 API + 反爬栈）
        # 不走 dry-run（要真启动浏览器），但跳过 OCR extractor
        self.screenshot_only = screenshot_only

        # 加载 OCR 配置
        with open(OCR_CONFIG_PATH, encoding="utf-8") as f:
            self.ocr_config = yaml.safe_load(f) or {}

        # 截图目录
        self.screenshot_dir = Path(SCREENSHOT_PATH)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        # OCR 提取器（lazy 加载，避免硬依赖 paddleocr）
        self._ocr_extractor = None

        # 截图清理器
        self.screenshot_gc = ScreenshotGC(
            retention_days=SCREENSHOT_RETENTION_DAYS,
            screenshot_path=SCREENSHOT_PATH,
        )

    # ===== 截图相关 =====

    def _take_screenshot(
        self, category_name: str, page: int
    ) -> Path | None:
        """整页截图保存

        保存路径：data/screenshots/<batch_id>/<category>/page_<p>_<ts>.png
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would take screenshot for {category_name} page {page}")
            return None

        assert self.dp is not None, "Browser not initialized"

        # 截图目录
        shot_dir = self.screenshot_dir / self.batch_id / category_name
        shot_dir.mkdir(parents=True, exist_ok=True)

        # 文件名
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"page_{page:03d}_{ts}.{self.screenshot_format}"
        filepath = shot_dir / filename

        try:
            # DrissionPage 截图 API
            # full_page=True 截整页（含懒加载区域，需先滚动到底）
            self.dp.get_screenshot(
                path=str(filepath),
                full_page=True,
            )
            logger.info(f"Screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Screenshot failed for {category_name} page {page}: {e}")
            return None

    # ===== OCR 提取 =====

    def _get_ocr_extractor(self):
        """lazy 加载 OCR 提取器

        避免 paddleocr 硬依赖：未安装时降级到 mock（用于 dry-run）
        """
        if self._ocr_extractor is not None:
            return self._ocr_extractor

        if self.dry_run:
            # dry-run 模式：用 mock 提取器
            from jd_analytics.pipelines.ocr_extract import MockOcrExtractor
            self._ocr_extractor = MockOcrExtractor(self.ocr_config)
            return self._ocr_extractor

        try:
            from jd_analytics.pipelines.ocr_extract import PaddleOCRVLExtractor
            self._ocr_extractor = PaddleOCRVLExtractor(self.ocr_config)
        except ImportError as e:
            logger.error(
                f"PaddleOCR not installed, falling back to mock. "
                f"Install with: pip install paddleocr paddlepaddle. Error: {e}"
            )
            from jd_analytics.pipelines.ocr_extract import MockOcrExtractor
            self._ocr_extractor = MockOcrExtractor(self.ocr_config)

        return self._ocr_extractor

    def _run_ocr(
        self,
        screenshot_path: Path,
        category_name: str,
        keyword: str,
        page: int,
    ) -> list[dict[str, Any]]:
        """对截图跑 OCR，返回结构化商品列表

        返回 list[item_dict]，item_dict 字段对齐 drission_spider 的 _build_item

        Args:
            screenshot_path: 截图文件路径
            category_name: 品类名（参数传递，不靠实例状态）
            keyword: 搜索关键词
            page: 页码
        """
        extractor = self._get_ocr_extractor()
        items = extractor.extract_from_screenshot(
            screenshot_path=screenshot_path,
            category_name=category_name,
            keyword=keyword,
            page=page,
            batch_id=self.batch_id,
            month=self.month,
        )
        return items

    # ===== 重写 crawl_category（P0-2：去掉无用的 listen.start/stop）=====

    def crawl_category(self, category: dict[str, Any]) -> list[dict[str, Any]]:
        """OCR 路线爬取单个品类

        P0-2 修复（云长 review）：父类 `crawl_category` 在开头调
        `dp.listen.start(JD_SEARCH_API_PATTERN)` 监听 JSON 接口，
        但 OCR 路线不解析 JSON，监听纯属浪费且会触发额外网络请求。
        此处重写为：跳过 listen，直接走 page loop。

        限速 / 单 IP 日配额 / 点击下一页等行为复用父类逻辑。
        """
        name = category["name"]
        keyword = (category.get("aliases") or [name])[0]
        cid2 = category.get("cid2", "")
        cid3 = category.get("cid3", "")
        logger.info(
            f"=== [OCR] 开始爬品类 {name} "
            f"(keyword={keyword}, cid2={cid2}, cid3={cid3}) ==="
        )

        assert self.dp is not None, "Browser not initialized"

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

            # 点击"下一页" + 限速（复用父类）
            if not self._click_next_page():
                logger.info(f"No more pages for {name}")
                break

            page += 1
            # 单 IP 慢爬防封：每页间 sleep + 随机抖动
            import random
            if random.random() < 0.05:
                sleep_sec = random.uniform(10.0, 20.0)
                logger.info(f"  long pause {sleep_sec:.1f}s (5% chance, 仿真阅读)")
            else:
                sleep_sec = self.page_sleep_seconds + random.uniform(0, 3.0)
                logger.info(f"  sleep {sleep_sec:.1f}s between pages")
            time.sleep(sleep_sec)

        logger.info(f"=== [OCR] 品类 {name} finished: {len(all_items)} items ===")
        return all_items

    # ===== 重写单页爬取 =====

    def _crawl_single_page(
        self, category_name: str, keyword: str, page: int
    ) -> list[dict[str, Any]]:
        """OCR 路线：访问页面 → 反爬检测 → 滚动 → 截图 → OCR 提取

        与 DrissionSpider._crawl_single_page 的区别：
        - 不监听 JSON 接口
        - 不解析 JSON
        - 改为截图 + OCR
        - P0-1：接入 `_check_after_page_load` 真正生效的 ban/captcha 检测
        """
        assert self.dp is not None

        # 上下文通过参数传递（不污染实例状态）
        # 1. 访问搜索页
        url = JD_SEARCH_URL.format(keyword=quote(keyword), page=page)
        if page == 1:
            self.dp.get(url)
            self.daily_counter += 1

            # 2. 反爬检测（P0-1 修复：每次 get 后调用）
            status = self._check_after_page_load(url)
            if status == "skip":
                logger.warning(
                    f"[{category_name}] page {page} skipped: captcha/ban"
                )
                return []
            if status == "wait_retry":
                # ban 退避后重试一次
                logger.info(f"[{category_name}] page {page} retrying after ban backoff")
                self.dp.get(url)
                status2 = self._check_after_page_load(url)
                if status2 != "ok":
                    logger.warning(
                        f"[{category_name}] page {page} retry failed: {status2}"
                    )
                    return []

        # 3. 滚动到页底加载懒加载内容（截图前必须）
        try:
            self.dp.scroll.to_bottom()
            # 给懒加载一点时间
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Scroll failed on page {page}: {e}")

        # 3. 截图
        screenshot_path = self._take_screenshot(category_name, page)
        if not screenshot_path:
            logger.warning(f"No screenshot for page {page}, skipping OCR")
            return []

        # screenshot_only 模式：截图后不跑 OCR（验证截图 API + 反爬栈用）
        if self.screenshot_only:
            logger.info(
                f"[{category_name}] page {page} screenshot-only mode, "
                f"skipping OCR"
            )
            return []

        # 4. OCR 提取
        page_items = self._run_ocr(screenshot_path, category_name, keyword, page)
        logger.info(
            f"[{category_name}] page {page} OCR extracted: {len(page_items)} items"
        )

        # 5. 通过 pipeline 链处理（复用 drission_spider 的 pipeline）
        # 链序：validation → dedup → storage → cold_storage
        processed: list[dict[str, Any]] = []
        for item in page_items:
            try:
                item = self.validation_pipeline.process_item(item, spider=None)
                item = self.dedup_pipeline.process_item(item, spider=None)
                self.storage_pipeline.process_item(item, spider=None)
                # ColdStorage：原始 JSON 落 parquet 作 debug（90 天 GC）
                self.cold_storage_pipeline.process_item(item, spider=None)
                processed.append(item)
            except Exception as e:
                logger.debug(f"Pipeline dropped item: {e}")

        return processed

    # ===== 重写 run（加截图 GC + P1-5 dry-run 不启动浏览器）=====

    def run(self) -> dict[str, int]:
        """执行爬取 - 在 DrissionSpider.run 前加截图 GC

        P1-5 修复（云长 review）：dry-run 模式完全跳过浏览器启动，
        只验证代码路径（pipeline 链 / OCR 配置加载 / GC 调用）。

        DrissionSpider.run 第一行就是 `self._init_browser()`，
        dry-run 必须在此短路。
        """
        # 爬取前清理过期截图
        if self.ocr_config.get("retention", {}).get("run_before_crawl", True):
            logger.info("Running screenshot GC before crawl...")
            self.screenshot_gc.cleanup()

        if self.dry_run:
            return self._dry_run_path()

        return super().run()

    def _dry_run_path(self) -> dict[str, int]:
        """dry-run 验证路径：不启动浏览器，只走通 pipeline 链

        验证项：
        - OCR 配置可加载（已在 __init__ 完成）
        - ScreenshotGC 可调用（已在 run() 开头完成）
        - pipeline 链可实例化（validation / dedup / storage）
        - OCR extractor 可 lazy 加载（MockOcrExtractor）
        - 各品类配置可遍历
        """
        logger.warning("=" * 60)
        logger.warning("DRY-RUN MODE: 不启动浏览器、不访问京东、不跑真实 OCR")
        logger.warning("只验证代码路径（配置加载 / pipeline 链 / OCR extractor）")
        logger.warning("=" * 60)

        results: dict[str, int] = {}

        # 验证 OCR extractor 可加载（mock）
        try:
            extractor = self._get_ocr_extractor()
            logger.info(f"OCR extractor loaded: {extractor.__class__.__name__}")
        except Exception as e:
            logger.error(f"OCR extractor load failed: {e}")
            return results

        # 遍历品类配置，验证可解析
        if self.trial and self.categories_config.get("trial_category"):
            cats = [self.categories_config["trial_category"]]
        else:
            cats = [
                c for c in self.categories_config.get("categories", [])
                if c.get("cid2") and c.get("cid3")
            ]

        for cat in cats:
            name = cat["name"]
            logger.info(f"[DRY-RUN] 品类 {name} 配置 OK (cid2={cat.get('cid2')})")
            results[name] = 0

        logger.info(f"[DRY-RUN] Done. Verified {len(results)} categories.")
        return results


def main():
    parser = argparse.ArgumentParser(description="OCR 路线京东品类爬虫")
    parser.add_argument("--batch-id", help="批次 ID（默认 UTC 时间戳）")
    parser.add_argument("--month", help="YYYY-MM，默认本月")
    parser.add_argument(
        "--trial", action="store_true", help="试爬模式（1 品类 × max_pages 页）"
    )
    parser.add_argument(
        "--category", help="只跑指定品类名（如 棉柔巾）"
    )
    parser.add_argument(
        "--max-pages", type=int, default=2,
        help="每个品类最大爬取页数（试爬默认 2 页）",
    )
    parser.add_argument(
        "--headless", action="store_true", help="无头模式"
    )
    parser.add_argument(
        "--page-sleep", type=float, default=3.0,
        help="每页之间 sleep 秒数（默认 3.0，单 IP 慢爬防封）",
    )
    parser.add_argument(
        "--manual-login", action="store_true",
        help="启动浏览器后人工登录京东账号",
    )
    parser.add_argument(
        "--auto-login", action="store_true",
        help="用 --login-phone + --login-password 自动登录",
    )
    parser.add_argument(
        "--login-phone",
        default=os.environ.get("JD_LOGIN_PHONE", ""),
    )
    parser.add_argument(
        "--login-password",
        default=os.environ.get("JD_LOGIN_PASSWORD", ""),
    )
    parser.add_argument(
        "--login-wait", type=int, default=120,
    )
    parser.add_argument(
        "--user-data-path",
        default=r"C:\Users\23363\AppData\Local\Temp\drission_chrome_jd_profile",
    )
    # ===== OCR 路线专属参数 =====
    parser.add_argument(
        "--ocr-engine",
        default="paddleocr_vl",
        choices=["paddleocr_vl", "qwen_vl_ocr_api"],
        help="OCR 引擎（默认 paddleocr_vl 自部署）",
    )
    parser.add_argument(
        "--screenshot-format",
        default="png",
        choices=["png", "jpeg", "webp"],
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证代码路径，不实际访问京东、不跑 OCR",
    )
    parser.add_argument(
        "--screenshot-only",
        action="store_true",
        help="只截图不跑 OCR（验证截图 API + 反爬栈用，会真启动浏览器）",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    spider = OcrSpider(
        batch_id=args.batch_id,
        month=args.month,
        trial=args.trial,
        max_pages_per_category=args.max_pages,
        headless=args.headless,
        page_sleep_seconds=args.page_sleep,
        manual_login=args.manual_login,
        auto_login=args.auto_login,
        login_phone=args.login_phone,
        login_password=args.login_password,
        login_wait_seconds=args.login_wait,
        user_data_path=args.user_data_path,
        ocr_engine=args.ocr_engine,
        screenshot_format=args.screenshot_format,
        dry_run=args.dry_run,
        screenshot_only=args.screenshot_only,
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

    # 抓取完 → 聚合 Top30
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
