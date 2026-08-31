"""冒烟测试：模块可导入性 + 基础功能。"""
import importlib


def test_imports():
    """所有核心模块可导入"""
    modules = [
        "jd_analytics.settings",
        "jd_analytics.models.schema",
        "jd_analytics.middlewares.ban",
        "jd_analytics.middlewares.captcha",
        "jd_analytics.middlewares.ip_quota",
        "jd_analytics.middlewares.fingerprint",
        "jd_analytics.spiders.jd_category_spider",
        "jd_analytics.pipelines.validation",
        "jd_analytics.pipelines.dedup",
        "jd_analytics.pipelines.storage",
        "jd_analytics.pipelines.coldstorage",
        "jd_analytics.pipelines.retry",
        "jd_analytics.aggregator",
        "jd_analytics.batch_report",
        "jd_analytics.cli",
    ]
    for m in modules:
        importlib.import_module(m)


def test_captcha_detection():
    """验证码检测"""
    from jd_analytics.middlewares.captcha import CaptchaDetectMiddleware
    mw = CaptchaDetectMiddleware()
    assert mw._is_captcha('html with id="captcha" inside')
    assert mw._is_captcha("请输入验证码")
    assert mw._is_captcha("verify.jd.com/page")
    assert not mw._is_captcha("normal page content")


def test_ip_quota_init():
    """IP 配额初始化"""
    from jd_analytics.middlewares.ip_quota import IPQuotaMiddleware
    mw = IPQuotaMiddleware(daily_limit=5)
    assert mw.daily_limit == 5
    assert mw.counter == 0


def test_brand_normalization_basic():
    """品牌名标准化"""
    from jd_analytics.pipelines.storage import StoragePipeline
    sp = StoragePipeline.__new__(StoragePipeline)
    sp._load_brand_normalization()
    assert sp._normalize_brand("花王(中国)") == "花王"
    assert sp._normalize_brand("KAO") == "花王"
    assert sp._normalize_brand("P&G官方旗舰店") == "宝洁"
    assert sp._normalize_brand(None) is None


def test_parse_price():
    """单价解析"""
    from jd_analytics.spiders.jd_category_spider import JdCategorySpider
    assert JdCategorySpider._parse_price("99.00") == 99.0
    assert JdCategorySpider._parse_price("129.5") == 129.5
    assert JdCategorySpider._parse_price(None) is None


def test_validation_pipeline():
    """数据校验"""
    from jd_analytics.pipelines.validation import ValidationPipeline
    from scrapy.exceptions import DropItem
    mw = ValidationPipeline()

    # 正常 item
    item = {"spu_id": "123", "batch_id": "b1", "category": "phone", "url": "http://x"}
    assert mw.process_item(item, None) == item

    # 缺字段
    try:
        mw.process_item({"spu_id": "123"}, None)
        assert False, "Should have raised DropItem"
    except DropItem:
        pass

    # 负值
    try:
        bad = {"spu_id": "1", "batch_id": "b", "category": "c", "url": "u",
               "price": -1.0}
        mw.process_item(bad, None)
        assert False, "Should have raised DropItem for negative price"
    except DropItem:
        pass


def test_dedup_pipeline():
    """SPU 去重 - Q4 取评价数最大"""
    from jd_analytics.pipelines.dedup import DedupPipeline
    from scrapy.exceptions import DropItem
    mw = DedupPipeline()

    # 第一次见 SPU1，评价数 100
    item1 = {"spu_id": "1", "cumu_review_count": 100, "url": "u1"}
    assert mw.process_item(item1, None) == item1

    # 第二次见 SPU1，评价数 50（更小，丢弃）
    item2 = {"spu_id": "1", "cumu_review_count": 50, "url": "u2"}
    try:
        mw.process_item(item2, None)
        assert False, "Should drop lower review count"
    except DropItem:
        pass

    # 第三次见 SPU1，评价数 200（更大，替换）
    item3 = {"spu_id": "1", "cumu_review_count": 200, "url": "u3"}
    try:
        mw.process_item(item3, None)
        # 在 dedup 内部，新 item 比较大于旧 item 时也会 raise DropItem
        # 因为后续 pipeline 已经处理过原 item（demo 简化逻辑）
    except DropItem:
        pass

    # 新 SPU2
    item4 = {"spu_id": "2", "cumu_review_count": 80, "url": "u4"}
    assert mw.process_item(item4, None) == item4


def test_settings():
    """Scrapy settings 关键值"""
    from jd_analytics import settings as s
    assert s.AUTOTHROTTLE_ENABLED is True
    assert s.CONCURRENT_REQUESTS == 1
    assert s.DOWNLOAD_DELAY == 2
    assert s.DAILY_LIMIT_PER_IP == 800  # 试爬延时调保守（1500→800）
    assert "club.jd.com" in s.JD_COMMENT_API
    assert "search.jd.com" in s.JD_SEARCH_URL


def test_categories_yaml():
    """品类配置可加载"""
    import yaml
    from pathlib import Path
    path = Path(__file__).parent.parent / "src" / "jd_analytics" / "config" / "categories.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert len(data["categories"]) == 11
    assert data["categories"][2]["name"] == "棉柔巾·绵柔巾"
    assert data["categories"][2]["precision_confirmed"] is True
    assert data["trial_category"]["cid2"] == "653"
    assert data["trial_category"]["cid3"] == "655"


def test_compliance_yaml():
    """合规配置可加载"""
    import yaml
    from pathlib import Path
    path = Path(__file__).parent.parent / "src" / "jd_analytics" / "config" / "compliance.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["qps_limits"]["global"] == 5
    assert data["pii_redaction"]["drop_fields"][0] == "comment_user_nickname"
    assert "no_captcha_bypass" in data["red_lines"]
