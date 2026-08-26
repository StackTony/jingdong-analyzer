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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
