"""冒烟测试：模块可导入性 + 基础功能。"""
import importlib

import pytest


def test_imports():
    """所有核心模块可导入"""
    modules = [
        "jd_analytics.settings",
        "jd_analytics.models.schema",
        "jd_analytics.middlewares.proxy",
        "jd_analytics.middlewares.behavior",
        "jd_analytics.middlewares.captcha",
        "jd_analytics.middlewares.ban",
        "jd_analytics.middlewares.ip_quota",
        "jd_analytics.middlewares.fingerprint",
        "jd_analytics.spiders.item_spider",
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


def test_proxy_health_score():
    """ProxyHealth 评分算法基础测试"""
    from jd_analytics.middlewares.proxy import ProxyHealth
    h = ProxyHealth(success_count=8, failure_count=2, avg_latency=1.0)
    assert 0 < h.success_rate <= 1.0
    assert 0 < h.score < 1.0


def test_captcha_detection():
    """验证码检测"""
    from jd_analytics.middlewares.captcha import CaptchaDetectMiddleware
    mw = CaptchaDetectMiddleware()
    assert mw._is_captcha('html with id="captcha" inside')
    assert mw._is_captcha("请输入验证码")
    assert mw._is_captcha("verify.jd.com/page")
    assert not mw._is_captcha("normal page content")


def test_ip_quota_reset():
    """IP 配额午夜重置"""
    from jd_analytics.middlewares.ip_quota import IPQuotaMiddleware
    mw = IPQuotaMiddleware(daily_limit=5)
    assert mw.daily_limit == 5
    # counter 初始为空
    assert len(mw.counter) == 0


def test_brand_normalization_basic():
    """品牌名标准化基础测试"""
    from jd_analytics.pipelines.storage import StoragePipeline
    # 不直接实例化（需要 DB），仅测试 _normalize_brand
    sp = StoragePipeline.__new__(StoragePipeline)
    sp._load_brand_normalization()
    assert sp._normalize_brand("花王(中国)") == "花王"
    assert sp._normalize_brand("KAO") == "花王"
    assert sp._normalize_brand("P&G官方旗舰店") == "宝洁"
    assert sp._normalize_brand(None) is None


def test_parse_review_count():
    """评价数解析"""
    from jd_analytics.spiders.item_spider import JdItemSpider
    assert JdItemSpider._parse_review_count("已有 300000 人评价") == 300000
    assert JdItemSpider._parse_review_count("已有 1,234 人评价") == 1234
    assert JdItemSpider._parse_review_count(None) is None
    assert JdItemSpider._parse_review_count("no count") is None


def test_parse_price():
    """单价解析"""
    from jd_analytics.spiders.item_spider import JdItemSpider
    assert JdItemSpider._parse_price("￥99.00") == 99.0
    assert JdItemSpider._parse_price("129.5") == 129.5
    assert JdItemSpider._parse_price(None) is None


def test_behavior_delay_distribution():
    """行为层延迟分布"""
    from jd_analytics.middlewares.behavior import BehaviorMiddleware
    mw = BehaviorMiddleware()
    delays = [mw._weighted_delay() for _ in range(1000)]
    # 90% 应在 1-5s
    short = sum(1 for d in delays if 1 <= d <= 5)
    long = sum(1 for d in delays if 10 <= d <= 30)
    assert short + long == 1000
    assert short > 800  # ~90%
