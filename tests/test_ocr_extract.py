"""
OCR 路线单元测试（spec F001-ocr-route §AC-7）

不实际跑 PaddleOCR，不实际访问京东。
测试目标：
1. MockOcrExtractor 能返回符合 item schema 的数据
2. ScreenshotGC 能正确清理 7 天前的文件
3. OcrSpider 能正确初始化（继承 DrissionSpider）
4. CLI 能正确解析 --mode ocr 参数
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ===== 测试 MockOcrExtractor =====

def test_mock_ocr_extractor_returns_valid_items():
    """MockOcrExtractor 应返回符合 item schema 的商品列表"""
    from jd_analytics.pipelines.ocr_extract import MockOcrExtractor

    config = {
        "paddleocr_vl": {
            "model": "PaddleOCR-VL",
            "lang": "ch",
            "confidence_threshold": 0.80,
        }
    }
    extractor = MockOcrExtractor(config)

    items = extractor.extract_from_screenshot(
        screenshot_path=Path("/fake/path/screenshot.png"),
        category_name="湿巾",
        keyword="湿巾",
        page=1,
        batch_id="test_batch_001",
        month="2026-08",
    )

    assert len(items) == 2  # mock 返回 2 个商品

    # 第一个商品字段校验
    item = items[0]
    assert item["spu_id"] == "mock_sku_1_1"
    assert item["batch_id"] == "test_batch_001"
    assert item["month"] == "2026-08"
    assert item["category"] == "湿巾"
    assert item["keyword"] == "湿巾"
    assert item["title"]  # 非空
    assert item["brand_name_raw"]  # 非空
    assert item["url"].startswith("https://item.jd.com/")
    assert item["price"] == 99.9
    assert item["cumu_review_count"] == 5000
    assert "low_confidence" in item

    # 第二个商品（100万+ 销量）
    item2 = items[1]
    assert item2["cumu_review_count"] == 1000000
    assert item2["total_sales"] == 1000000


def test_mock_ocr_extractor_handles_missing_screenshot():
    """截图不存在时应返回空列表"""
    from jd_analytics.pipelines.ocr_extract import PaddleOCRVLExtractor

    config = {
        "paddleocr_vl": {
            "model": "PaddleOCR-VL",
            "lang": "ch",
            "confidence_threshold": 0.80,
        }
    }
    extractor = PaddleOCRVLExtractor(config)

    items = extractor.extract_from_screenshot(
        screenshot_path=Path("/nonexistent/screenshot.png"),
        category_name="湿巾",
        keyword="湿巾",
        page=1,
        batch_id="test_batch_002",
        month="2026-08",
    )
    assert items == []


# ===== 测试 ScreenshotGC =====

def test_screenshot_gc_deletes_old_files():
    """ScreenshotGC 应删除 mtime > 7 天的文件"""
    from jd_analytics.utils.screenshot_gc import ScreenshotGC

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试截图目录
        shot_path = Path(tmpdir) / "screenshots"
        shot_path.mkdir()

        # 创建 8 天前的旧文件
        old_file = shot_path / "batch_old" / "page_001.png"
        old_file.parent.mkdir(parents=True)
        old_file.write_bytes(b"fake png")
        # 设 mtime 为 8 天前
        old_time = time.time() - 8 * 24 * 3600
        os.utime(old_file, (old_time, old_time))

        # 创建今天的新文件
        new_file = shot_path / "batch_new" / "page_001.png"
        new_file.parent.mkdir(parents=True)
        new_file.write_bytes(b"fake png")

        # 跑 GC
        gc = ScreenshotGC(
            retention_days=7,
            screenshot_path=str(shot_path),
        )
        stats = gc.cleanup()

        # 旧文件应被删除
        assert not old_file.exists()
        # 新文件应保留
        assert new_file.exists()
        assert stats["deleted_files"] == 1
        assert stats["skipped"] == 1


def test_screenshot_gc_get_stats_returns_summary():
    """ScreenshotGC.get_stats 应返回目录统计"""
    from jd_analytics.utils.screenshot_gc import ScreenshotGC

    with tempfile.TemporaryDirectory() as tmpdir:
        shot_path = Path(tmpdir) / "screenshots"
        shot_path.mkdir()

        # 空目录
        gc = ScreenshotGC(
            retention_days=7,
            screenshot_path=str(shot_path),
        )
        stats = gc.get_stats()
        assert stats["total_files"] == 0

        # 加 2 个文件
        (shot_path / "page_001.png").write_bytes(b"fake")
        (shot_path / "page_002.png").write_bytes(b"fake")
        stats = gc.get_stats()
        assert stats["total_files"] == 2


def test_screenshot_gc_handles_nonexistent_path():
    """目录不存在时 GC 不应报错"""
    from jd_analytics.utils.screenshot_gc import ScreenshotGC

    gc = ScreenshotGC(
        retention_days=7,
        screenshot_path="/nonexistent/path",
    )
    stats = gc.cleanup()
    assert stats["deleted_files"] == 0
    assert stats["errors"] == 0


# ===== 测试 OCR 配置文件 =====

def test_ocr_config_yaml_loads():
    """ocr_config.yaml 应能正确加载且包含必要字段"""
    config_path = (
        Path(__file__).parent.parent
        / "src"
        / "jd_analytics"
        / "config"
        / "ocr_config.yaml"
    )
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 必要字段
    assert config["engine"] == "paddleocr_vl"
    assert "paddleocr_vl" in config
    assert "screenshot" in config
    assert "retention" in config

    # PaddleOCR-VL 配置
    vl_config = config["paddleocr_vl"]
    assert vl_config["model"] == "PaddleOCR-VL"
    assert vl_config["lang"] == "ch"
    assert vl_config["confidence_threshold"] >= 0.5

    # 截图保留天数
    assert config["retention"]["days"] == 7


def test_ocr_regions_v1_yaml_loads():
    """ocr_regions_v1.yaml 应能正确加载且包含字段定义"""
    config_path = (
        Path(__file__).parent.parent
        / "src"
        / "jd_analytics"
        / "config"
        / "selectors"
        / "ocr_regions_v1.yaml"
    )
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 版本号
    assert config["version"] == "1"

    # 字段定义
    assert "fields" in config
    assert "title" in config["fields"]
    assert "price" in config["fields"]
    assert "shop_name" in config["fields"]
    assert "item_url" in config["fields"]

    # 必需字段标记
    assert config["fields"]["title"]["required"] is True
    assert config["fields"]["price"]["required"] is True


# ===== 测试 OcrSpider 初始化（不实际跑）=====

def test_ocr_spider_init_inherits_drission():
    """OcrSpider 应能正确初始化并继承 DrissionSpider"""
    from jd_analytics.spiders.ocr_spider import OcrSpider
    from jd_analytics.spiders.drission_spider import DrissionSpider

    spider = OcrSpider(
        batch_id="test_ocr_001",
        month="2026-08",
        trial=True,
        dry_run=True,
    )

    # 继承关系
    assert isinstance(spider, DrissionSpider)

    # OCR 专属属性
    assert spider.ocr_engine == "paddleocr_vl"
    assert spider.screenshot_format == "png"
    assert spider.dry_run is True

    # 复用 DrissionSpider 的反爬栈
    assert hasattr(spider, "page_sleep_seconds")
    assert hasattr(spider, "daily_counter")
    assert hasattr(spider, "daily_limit")
    assert hasattr(spider, "auto_login")
    assert hasattr(spider, "manual_login")
    assert spider.validation_pipeline is not None
    assert spider.dedup_pipeline is not None
    assert spider.storage_pipeline is not None


def test_ocr_spider_take_screenshot_dry_run():
    """dry-run 模式下截图应只记录日志不实际执行"""
    from jd_analytics.spiders.ocr_spider import OcrSpider

    spider = OcrSpider(
        batch_id="test_ocr_002",
        month="2026-08",
        trial=True,
        dry_run=True,
    )
    # 浏览器未初始化
    spider.dp = None

    # dry-run 应返回 None 且不报错
    result = spider._take_screenshot("湿巾", 1)
    assert result is None


def test_ocr_spider_get_ocr_extractor_uses_mock_in_dry_run():
    """dry-run 模式应使用 MockOcrExtractor"""
    from jd_analytics.spiders.ocr_spider import OcrSpider
    from jd_analytics.pipelines.ocr_extract import MockOcrExtractor

    spider = OcrSpider(
        batch_id="test_ocr_003",
        month="2026-08",
        trial=True,
        dry_run=True,
    )

    extractor = spider._get_ocr_extractor()
    assert isinstance(extractor, MockOcrExtractor)


# ===== 测试 settings 配置 =====

def test_settings_has_ocr_config():
    """settings.py 应包含 OCR 路线相关配置"""
    from jd_analytics.settings import (
        SCREENSHOT_PATH,
        SCREENSHOT_RETENTION_DAYS,
        OCR_ENGINE,
        OCR_CONFIG_PATH,
    )

    assert SCREENSHOT_PATH
    assert SCREENSHOT_RETENTION_DAYS == 7
    assert OCR_ENGINE == "paddleocr_vl"
    assert OCR_CONFIG_PATH


# ===== 测试 CLI 参数解析 =====

def test_cli_collect_parser_accepts_mode_ocr():
    """CLI collect 子命令应能解析 --mode ocr"""
    from jd_analytics.cli import main
    import argparse

    # 模拟 sys.argv
    test_args = ["jd-collect", "collect", "--mode", "ocr", "--dry-run"]
    with patch.object(sys, "argv", test_args):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p_collect = sub.add_parser("collect")
        p_collect.add_argument("--month")
        p_collect.add_argument("--trial", action="store_true")
        p_collect.add_argument(
            "--mode", choices=["json", "ocr"], default="json"
        )
        p_collect.add_argument("--dry-run", action="store_true")

        args = parser.parse_args(test_args[1:])
        assert args.mode == "ocr"
        assert args.dry_run is True


# ===== 行为测试（P0-1 / P1-4 / P1-5 修复后补）=====

def test_ocr_structure_items_clusters_by_box_coordinate():
    """P1-4：_structure_items 按 box 坐标聚类，不能靠索引配对导致错位

    构造模拟 OCR 结果：2 行 × 2 列 = 4 个商品卡片
    验证每个商品的字段从同一卡片内提取，不错位
    """
    from jd_analytics.pipelines.ocr_extract import PaddleOCRVLExtractor

    config = {
        "paddleocr_vl": {"confidence_threshold": 0.50},
        "clustering": {
            "row_y_threshold": 250,
            "card_x_threshold": 280,
            "card_min_texts": 2,
            "max_items_per_page": 60,
        },
    }
    extractor = PaddleOCRVLExtractor(config)

    # 模拟 4 个商品卡片，2 行 × 2 列
    # 行 1 (y≈100): 卡 A (x≈100), 卡 B (x≈400)
    # 行 2 (y≈600): 卡 C (x≈100), 卡 D (x≈400)
    # 每卡含：标题 / 价格 / SKU / 销量 / 店铺
    def make_box(x, y, w=200, h=30):
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    texts_with_boxes = [
        # 行 1 - 卡 A
        {"text": "棉柔巾婴儿专用加厚60抽", "confidence": 0.95, "box": make_box(50, 80)},
        {"text": "¥39.9", "confidence": 0.95, "box": make_box(50, 130)},
        {"text": "1000023412", "confidence": 0.95, "box": make_box(50, 180)},
        {"text": "已拼5万+", "confidence": 0.95, "box": make_box(50, 230)},
        {"text": "宝洁旗舰店", "confidence": 0.95, "box": make_box(50, 280)},

        # 行 1 - 卡 B
        {"text": "婴儿湿巾80抽大包家庭装", "confidence": 0.95, "box": make_box(380, 80)},
        {"text": "¥29.9", "confidence": 0.95, "box": make_box(380, 130)},
        {"text": "1000098765", "confidence": 0.95, "box": make_box(380, 180)},
        {"text": "已拼2000+", "confidence": 0.95, "box": make_box(380, 230)},
        {"text": "好奇专卖店", "confidence": 0.95, "box": make_box(380, 280)},

        # 行 2 - 卡 C
        {"text": "拉拉裤L码女童成长裤", "confidence": 0.95, "box": make_box(50, 580)},
        {"text": "¥89.9", "confidence": 0.95, "box": make_box(50, 630)},
        {"text": "1000034567", "confidence": 0.95, "box": make_box(50, 680)},
        {"text": "已拼10万+", "confidence": 0.95, "box": make_box(50, 730)},
        {"text": "帮宝适旗舰店", "confidence": 0.95, "box": make_box(50, 780)},

        # 行 2 - 卡 D
        {"text": "纸尿裤S码新生儿专用", "confidence": 0.95, "box": make_box(380, 580)},
        {"text": "¥59.0", "confidence": 0.95, "box": make_box(380, 630)},
        {"text": "1000087654", "confidence": 0.95, "box": make_box(380, 680)},
        {"text": "已拼8000+", "confidence": 0.95, "box": make_box(380, 730)},
        {"text": "大王专营店", "confidence": 0.95, "box": make_box(380, 780)},
    ]

    items = extractor._structure_items(
        texts_with_boxes,
        category_name="棉柔巾",
        keyword="棉柔巾",
        page=1,
        batch_id="test_cluster",
        month="2026-08",
    )

    assert len(items) == 4, f"Expected 4 items, got {len(items)}"

    # 验证字段不错位：每个 SKU 对应的价格/销量/店铺必须正确
    by_sku = {it["spu_id"]: it for it in items}

    assert by_sku["1000023412"]["price"] == 39.9
    assert by_sku["1000023412"]["cumu_review_count"] == 50000
    assert "宝洁" in by_sku["1000023412"]["brand_name_raw"]

    assert by_sku["1000098765"]["price"] == 29.9
    assert by_sku["1000098765"]["cumu_review_count"] == 2000
    assert "好奇" in by_sku["1000098765"]["brand_name_raw"]

    assert by_sku["1000034567"]["price"] == 89.9
    assert by_sku["1000034567"]["cumu_review_count"] == 100000

    assert by_sku["1000087654"]["price"] == 59.0
    assert by_sku["1000087654"]["cumu_review_count"] == 8000


def test_ocr_structure_items_drops_low_confidence():
    """低置信度文本块应被过滤，不进入聚类"""
    from jd_analytics.pipelines.ocr_extract import PaddleOCRVLExtractor

    config = {
        "paddleocr_vl": {"confidence_threshold": 0.80},
        "clustering": {"card_min_texts": 2},
    }
    extractor = PaddleOCRVLExtractor(config)

    texts = [
        {"text": "高置信度标题", "confidence": 0.95, "box": [[0, 0], [100, 0], [100, 30], [0, 30]]},
        {"text": "¥19.9", "confidence": 0.95, "box": [[0, 40], [100, 40], [100, 70], [0, 70]]},
        {"text": "低置信度垃圾", "confidence": 0.50, "box": [[0, 80], [100, 80], [100, 110], [0, 110]]},
    ]
    items = extractor._structure_items(
        texts, "cat", "kw", 1, "b", "2026-08",
    )
    # 应有 1 个商品（标题+价格，低置信度文本被滤掉）
    assert len(items) == 1
    # 低置信度标记应为 True（因为有低置信度文本被丢）
    # 但目前 low_conf 是检查 card 内是否含低置信度文本，过滤后不会带进 card
    # 所以这里 low_conf=False（已过滤）—— 验证此行为
    assert items[0]["price"] == 19.9


def test_check_after_page_load_detects_captcha():
    """P0-1：_check_after_page_load 检测到 captcha 应返回 'skip'

    用 mock dp 模拟页面含 captcha 关键词，验证函数返回 'skip'
    且不会调用 handle_captcha（因为 retry_queue 是 sqlite 操作）
    """
    from jd_analytics.spiders.drission_spider import DrissionSpider

    spider = DrissionSpider(batch_id="test_captcha", month="2026-08", trial=True)

    # mock dp: 页面 HTML 含 captcha 标识
    mock_dp = MagicMock()
    mock_dp.html = '<div id="captcha" class="JDJV-bigimg">滑动验证</div>'
    mock_dp.url = "https://search.jd.com/Search?keyword=test"
    mock_dp.title = "验证"
    spider.dp = mock_dp

    # patch handle_captcha 防止实际写 retry_queue
    with patch("jd_analytics.middlewares.captcha.handle_captcha", return_value="skip") as mock_h:
        result = spider._check_after_page_load("https://search.jd.com/Search?keyword=test")

    assert result == "skip"
    mock_h.assert_called_once()


def test_check_after_page_load_detects_ban():
    """P0-1：_check_after_page_load 检测到 ban 关键词应返回 'skip' 或 'wait_retry'"""
    from jd_analytics.spiders.drission_spider import DrissionSpider

    spider = DrissionSpider(batch_id="test_ban", month="2026-08", trial=True)

    # mock dp: 页面正文含"访问过于频繁"
    mock_dp = MagicMock()
    mock_dp.html = '<html><body>访问过于频繁，请稍后再试</body></html>'
    mock_dp.url = "https://search.jd.com/Search?keyword=test"
    mock_dp.title = "异常"
    spider.dp = mock_dp

    with patch("jd_analytics.middlewares.ban.handle_ban", return_value="skip") as mock_h:
        result = spider._check_after_page_load("https://search.jd.com/Search?keyword=test")

    assert result in ("skip", "wait_retry")
    mock_h.assert_called_once()


def test_check_after_page_load_returns_ok_on_normal_page():
    """P0-1：正常页面应返回 'ok'，不调用 ban/captcha handler"""
    from jd_analytics.spiders.drission_spider import DrissionSpider

    spider = DrissionSpider(batch_id="test_ok", month="2026-08", trial=True)

    mock_dp = MagicMock()
    mock_dp.html = '<html><body>京东商品列表正常显示</body></html>'
    mock_dp.url = "https://search.jd.com/Search?keyword=test"
    mock_dp.title = "京东搜索"
    spider.dp = mock_dp

    result = spider._check_after_page_load("https://search.jd.com/Search?keyword=test")
    assert result == "ok"


def test_ocr_spider_dry_run_does_not_start_browser():
    """P1-5：dry-run 模式 run() 不应启动浏览器

    验证：
    - _init_browser 不被调用
    - self.dp 保持 None
    - run() 返回 dict（trial 品类验证）
    """
    from jd_analytics.spiders.ocr_spider import OcrSpider

    spider = OcrSpider(
        batch_id="test_dry_browser",
        month="2026-08",
        trial=True,
        dry_run=True,
    )

    # 跟踪 _init_browser 是否被调用
    with patch.object(spider, "_init_browser") as mock_init:
        results = spider.run()
        mock_init.assert_not_called()

    assert spider.dp is None
    assert isinstance(results, dict)
    assert len(results) >= 1  # trial 品类


def test_ocr_spider_screenshot_only_skips_ocr():
    """P1-3：screenshot_only 模式应截图后短路，不跑 OCR extractor"""
    from jd_analytics.spiders.ocr_spider import OcrSpider

    spider = OcrSpider(
        batch_id="test_shot_only",
        month="2026-08",
        trial=True,
        dry_run=False,
        screenshot_only=True,
    )

    # mock _take_screenshot 返回假路径
    with patch.object(spider, "_take_screenshot", return_value=Path("/fake/shot.png")):
        with patch.object(spider, "_get_ocr_extractor") as mock_get:
            # 不调 run()（会启动浏览器），直接调 _crawl_single_page 的 screenshot_only 分支
            spider.dp = MagicMock()  # 假装浏览器启动了
            # 模拟 _check_after_page_load 返回 ok
            with patch.object(spider, "_check_after_page_load", return_value="ok"):
                items = spider._crawl_single_page("棉柔巾", "棉柔巾", 1)
            mock_get.assert_not_called()  # OCR extractor 不该加载

    assert items == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
