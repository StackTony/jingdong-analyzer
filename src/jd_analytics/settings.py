"""
Scrapy settings — 反爬栈 v2（五层防御）

参考 spec §3 反爬栈 v2。
"""
import os
from pathlib import Path

# ===== 基础 =====
BOT_NAME = "jd_brand_analytics"
SPIDER_MODULES = ["jd_analytics.spiders"]
NEWSPIDER_MODULE = "jd_analytics.spiders"

# ===== 合规边界（spec §1.3） =====
COMPLIANCE_CONFIG = os.getenv(
    "COMPLIANCE_CONFIG",
    str(Path(__file__).parent / "config" / "compliance.yaml"),
)

# ===== 反爬栈 Layer 5: 调度层 =====
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2.0
AUTOTHROTTLE_MAX_DELAY = 60.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0

CONCURRENT_REQUESTS = 16              # 试爬后校准
CONCURRENT_REQUESTS_PER_IP = 1       # 避免单 IP 并发被检测
DOWNLOAD_DELAY = 0                    # 由 AUTOTHROTTLE 自适应

# 单 IP 日请求上限（spec §3.7）
DAILY_LIMIT_PER_IP = int(os.getenv("DAILY_LIMIT_PER_IP", "800"))

# ===== 反爬栈 Layer 1: 网络层（代理池）=====
PROXY_POOL_ENABLED = True
PROVIDERS_CONFIG = os.getenv(
    "PROVIDERS_CONFIG",
    str(Path(__file__).parent / "config" / "proxy_providers.yaml"),
)

# ===== 反爬栈 Layer 2: 指纹层 =====
USER_AGENT = None  # 由 fake-useragent 动态生成
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ],
}

# ===== 中间件链（spec §3 反爬栈 v2）=====
DOWNLOADER_MIDDLEWARES = {
    # Layer 5: 调度层（Scrapy 内置）
    "scrapy.downloadermiddlewares.throttle.AutoThrottleMiddleware": 100,

    # Layer 3: 行为层
    "jd_analytics.middlewares.behavior.BehaviorMiddleware": 200,

    # Layer 1: 网络层
    "jd_analytics.middlewares.proxy.ProxyRotationMiddleware": 300,
    "jd_analytics.middlewares.ip_quota.IPQuotaMiddleware": 310,

    # Layer 4: 检测层
    "jd_analytics.middlewares.captcha.CaptchaDetectMiddleware": 400,
    "jd_analytics.middlewares.ban.BanDetectMiddleware": 410,

    # Layer 2: 指纹层
    "jd_analytics.middlewares.fingerprint.FingerprintMiddleware": 500,

    # Scrapy 默认（最后）
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": 800,
    "scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware": 810,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": 900,
}

# ===== Pipelines =====
ITEM_PIPELINES = {
    "jd_analytics.pipelines.validation.ValidationPipeline": 100,    # pandera 校验
    "jd_analytics.pipelines.dedup.DedupPipeline": 200,             # SPU 去重
    "jd_analytics.pipelines.storage.StoragePipeline": 300,         # 入库
    "jd_analytics.pipelines.coldstorage.ColdStoragePipeline": 400, # Parquet 冷存
    "jd_analytics.pipelines.retry.RetryPipeline": 500,             # 失败入 retry_queue
}

# ===== JOBDIR 断点续传（spec §8.1）=====
JOBDIR_BASE = os.getenv("JOBDIR_BASE", ".scrapy/jobs")

# ===== 存储 =====
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/jd_analytics.db")
COLD_STORAGE_PATH = os.getenv(
    "COLD_STORAGE_PATH",
    str(Path(__file__).parent.parent.parent / "data" / "raw"),
)
COLD_STORAGE_RETENTION_DAYS = 90

# ===== 数据质量（spec §7）=====
DRIFT_DETECTION_ENABLED = True
DRIFT_THRESHOLD = 0.30  # diff > 30% 触发告警

# ===== 日志 =====
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"

# ===== Retry（spec §8.3）=====
RETRY_TIMES = 3
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504, 408]
RETRY_PRIORITY_MAP = {
    "network_timeout": 1,
    "http_403": 2,
    "http_429": 3,
    "captcha": 4,
    "parse_error": 5,
}
