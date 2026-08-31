"""
Scrapy settings — 极简模式（参考 JD_Spider）

设计原则：
- 直连单 IP + 慢爬防封
- 无 Playwright（京东列表页/评论 API 都是服务端渲染）
- 无代理池（铲屎官拍板单 IP 起步）
- 保留 AutoThrottle + ban/captcha 检测中间件
"""
import os
from pathlib import Path

# ===== 基础 =====
BOT_NAME = "jd_brand_analytics"
SPIDER_MODULES = ["jd_analytics.spiders"]
NEWSPIDER_MODULE = "jd_analytics.spiders"
ROBOTSTXT_OBEY = False  # 京东 robots 严格，按 spec §1.3 路径白名单手动控制

# ===== 限速（单 IP 慢爬防封）=====
# 铲屎官拍板：单 IP 模式 + 降低爬取速度
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3.0       # 起始延迟 3 秒
AUTOTHROTTLE_MAX_DELAY = 30.0        # 最大延迟 30 秒
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0  # 单并发，最保守

CONCURRENT_REQUESTS = 1               # 单并发，串行抓取
# CONCURRENT_REQUESTS_PER_IP 在 Scrapy 2.18 已废弃
DOWNLOAD_DELAY = 2                    # 基础 2 秒延迟 + AutoThrottle 自适应

# 单 IP 日请求上限（铲屎官要求"时间放长一点"防封）
# JD_Spider 199 页 × 60 商品 + 评论 API = 约 12000 请求/品类
# 单 IP 日阈值经验值 1000-3000，试爬保守取 800（从 1500 降）
DAILY_LIMIT_PER_IP = int(os.getenv("DAILY_LIMIT_PER_IP", "800"))

# ===== 重试 =====
RETRY_TIMES = 3
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504, 408]

# ===== 中间件（极简：只保留必要）=====
DOWNLOADER_MIDDLEWARES = {
    # 限速（Scrapy 内置 AutoThrottle，2.18 路径变化）
    # 由 EXTENSIONS 配置自动启用 AutoThrottle extension
    # 不需要在 DOWNLOADER_MIDDLEWARES 显式声明

    # 单 IP 日配额（防过载）
    "jd_analytics.middlewares.ip_quota.IPQuotaMiddleware": 200,

    # ban / captcha 检测
    "jd_analytics.middlewares.captcha.CaptchaDetectMiddleware": 300,
    "jd_analytics.middlewares.ban.BanDetectMiddleware": 400,

    # UA 轮换（轻量）
    "jd_analytics.middlewares.fingerprint.FingerprintMiddleware": 500,

    # Scrapy 默认
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": 800,
    "scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware": 810,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": 900,
}

# AutoThrottle 作为 extension 启用
EXTENSIONS = {
    "scrapy.extensions.throttle.AutoThrottle": 0,
}

# ===== Pipelines =====
ITEM_PIPELINES = {
    "jd_analytics.pipelines.validation.ValidationPipeline": 50,    # 数据校验
    "jd_analytics.pipelines.dedup.DedupPipeline": 100,             # SPU 去重
    "jd_analytics.pipelines.storage.StoragePipeline": 200,         # 入库
    "jd_analytics.pipelines.coldstorage.ColdStoragePipeline": 300, # Parquet 冷存
}

# ===== 存储 =====
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/jd_analytics.db")
COLD_STORAGE_PATH = os.getenv(
    "COLD_STORAGE_PATH",
    str(Path(__file__).parent.parent.parent / "data" / "raw"),
)
COLD_STORAGE_RETENTION_DAYS = 90

# ===== 日志 =====
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"

# ===== 合规配置 =====
COMPLIANCE_CONFIG = str(Path(__file__).parent / "config" / "compliance.yaml")

# ===== 京东 URL 模板（参考 JD_Spider）=====
# 列表页前 30 商品
JD_SEARCH_URL = (
    "https://search.jd.com/Search?keyword={keyword}&enc=utf-8"
    "&qrst=1&rt=1&stop=1&vt=2&cid2={cid2}&cid3={cid3}&page={page}&click=0"
)
# 列表页后 30 商品（异步加载）
JD_SEARCH_ASYNC_URL = (
    "https://search.jd.com/s_new.php?keyword={keyword}&enc=utf-8"
    "&qrst=1&rt=1&stop=1&vt=2&cid2={cid2}&cid3={cid3}&page={page}"
    "&scrolling=y&tpl=3_M&show_items={show_items}"
)
# 评论数 JSON API（直出 CommentCount/GoodCount 等）
JD_COMMENT_API = (
    "https://club.jd.com/comment/productCommentSummaries.action?referenceIds={spu_id}"
)
# 商品详情页
JD_ITEM_URL = "https://item.jd.com/{spu_id}.html"

# 11 品类 cid2/cid3 映射（spec §5 - 待 B+A 阶段确认）
# 参考 JD_Spider 手机 cid2=653, cid3=655
# 11 品类需要铲屎官/客户确认 cid2/cid3 后填入
CATEGORIES_CONFIG = str(Path(__file__).parent / "config" / "categories.yaml")

# 列表页数（JD_Spider 199 页 × 60 商品 = 11940）
MAX_PAGES_PER_CATEGORY = 199

# ===== OCR 路线配置（spec F001-ocr-route）=====
# 截图目录
SCREENSHOT_PATH = os.getenv(
    "SCREENSHOT_PATH",
    str(Path(__file__).parent.parent.parent / "data" / "screenshots"),
)
# 截图保留天数（铲屎官拍板 7 天）
SCREENSHOT_RETENTION_DAYS = int(os.getenv("SCREENSHOT_RETENTION_DAYS", "7"))
# OCR 引擎（paddleocr_vl | qwen_vl_ocr_api）
OCR_ENGINE = os.getenv("OCR_ENGINE", "paddleocr_vl")
# OCR 配置文件路径
OCR_CONFIG_PATH = str(Path(__file__).parent / "config" / "ocr_config.yaml")
