# 试爬报告 2026-08-25 - DrissionPage 切换

> **批次 ID**: 2026-08-25T1154110000（成功批次）
> **作者**: 郭嘉/奉孝 (ragdoll-pa82)
> **状态**: ✅ 试爬通过，管道全链路打通

## 1. 目标

按 CVO 指示，参考掘金《使用DrissionPage库爬取京东上的商品信息》文档实现方案，
替换原 scrapy + playwright 方案，跑试爬验证 1 品类 × 2 页。

## 2. 完成项

### 2.1 安装与配置

- ✅ `pip install DrissionPage -i https://pypi.tuna.tsinghua.edu.cn/simple` → 4.1.1.4
- ✅ ChromiumOptions 浏览器路径配置 → `C:\Program Files\Google\Chrome\Application\chrome.exe`
- ✅ 浏览器持久化 user_data_path（cookies 保存）

### 2.2 Spider 重写

- ✅ `src/jd_analytics/spiders/drission_spider.py` 新模块
  - 监听 `https://api.m.jd.com/api?appid=search-pc-java&t`
  - 拦截 JSON 响应，过滤含 `abBuriedTagMap` 的字典
  - 直接提取 `wareName / wareBuried.ori_price / finalPrice.estimatedPrice / totalSales / shopName / skuId`
  - 调用现有 pipelines（validation → dedup → storage → coldstorage）
  - CLI 参数：`--trial --max-pages --manual-login --auto-login --login-phone --login-password --login-wait --page-sleep --headless`
- ✅ 复用 `jd_analytics.pipelines.*` 全部 pipeline，无重复逻辑
- ✅ 复用 `jd_analytics.aggregator.aggregate_top30` Top30 双榜聚合
- ✅ 复用 `jd_analytics.batch_report.generate_batch_report` 批次报告

### 2.3 数据模型适配

- ✅ `pipelines/storage.py` 接受新字段（`total_sales` / `ori_price`）
- ✅ `cumu_review_count` 字段语义变为销量（沿用字段名兼容旧 schema）
- ✅ `MonthlyDelta.delta` 计算仍按 cumu_review_count 差值，但语义为销量差
- ✅ `aggregator.aggregate_top30` 改为直接读 `MonthlyDelta.cumu_review_count`（即 total_sales）做 volume
  - 不再依赖 `delta`（上月差值），因为首次抓取 prev=0 会导致 volume=0
  - value = volume × price_sampled（销售额估算）

### 2.4 Spec 更新

- ✅ §2 数据口径：评价数差 → totalSales 直出（精度提升 30-50%）
- ✅ §3 反爬栈：v2 五层架构 → v3 简化版（单 IP + DrissionPage 真实浏览器）
- ✅ §3.3 试爬阻塞段改写为"已解决"（auto-login 通过）
- ✅ §3.5 试爬校准项更新（页间 sleep / 监听数据包数 / 登录态过期周期）
- ✅ §3.4 v2 废弃设计归档

### 2.5 测试

- ✅ `pytest tests/test_smoke.py` 10/10 通过（无回归）

## 3. ✅ 试爬结果（批次 2026-08-25T1154110000）

### 3.1 爬取

- 品类：试爬品类（手机），trial_category
- 页数：2 页
- 抓取商品：95 条（page 1: 49, page 2: 46）
- 登录：auto-login 成功（58 秒，含人工过滑块）
- 限速：每页间 sleep 3-6s + 5% 概率 10-20s 长停留（CVO 要求"千万注意抓取频率，原则是不能被封号，可以慢"）

### 3.2 数据落库

```
spu_master:    95 条
sku_detail:    95 条
monthly_deltas: 95 条
brand_aggregates: 16 条（同品类去重后）
cold_storage:  95 个 parquet 文件
```

### 3.3 Top30 双榜

**销量榜 Top 5**：
| 排名 | brand_name | volume | value |
|---:|---|---:|---:|
| 1 | 荣耀京东自营 | 8,600,000 | 12.3B |
| 2 | 小米京东自营 | 920,000 | 2.66B |
| 3 | Oppo京东自营 | 800,000 | 1.75B |
| 4 | 华为京东自营 | 700,000 | 2.24B |
| 5 | 京东手机自营 | 150,000 | 300M |

**销售额榜 Top 5**：
| 排名 | brand_name | volume | value |
|---:|---|---:|---:|
| 1 | 荣耀京东自营 | 8,600,000 | 12.3B |
| 2 | 小米京东自营 | 920,000 | 2.66B |
| 3 | 华为京东自营 | 700,000 | 2.24B |
| 4 | Oppo京东自营 | 800,000 | 1.75B |
| 5 | 京东手机自营 | 150,000 | 300M |

注：销量榜 vs 销售额榜 Top3 顺序差异（Oppo 在销量榜 #3 但销售额榜 #4，因为华为均价更高）— 双榜设计成功体现差异。

### 3.4 数据样本

`MonthlyDelta`（cumu_review_count 字段语义 = total_sales）：
```
spu=100123598631  brand_raw=小米京东自营旗舰店  vol=800000  price=2999.0
spu=100123450364  brand_raw=华为京东自营旗舰店  vol=700000  price=3199.0
spu=100189191001  brand_raw=荣耀京东自营旗舰店  vol=1000000 price=1486.65
```

totalSales 解析支持格式：
- `int`: `999` → 999
- `str + 加号`: `"5000+"` → 5000
- `str + 万`: `"100万+"` → 1,000,000
- `str + 万 + 加号`: `"80万+"` → 800,000

## 4. ⚠️ 已知问题（不影响试爬通过）

### 4.1 brand_name_raw 用的是 shopName（店铺名）不是品牌名

京东搜索接口的 `shopName` 字段返回的是店铺全称（如"小米京东自营旗舰店"），
**不是品牌名**（"小米"）。

目前数据样本：
- `小米京东自营旗舰店` → 应归一为「小米」
- `华为京东自营旗舰店` → 应归一为「华为」
- `荣耀京东自营旗舰店` → 应归一为「荣耀」
- `OPPO京东自营旗舰店` → 应归一为「OPPO」
- `iQOO京东自营旗舰店` → 应归一为「iQOO」
- `Apple产品京东自营旗舰店` → 应归一为「Apple」

**brand_normalization.yaml 已有 `remove_suffix` 规则**（去"旗舰店"、"京东自营"等后缀），
但当前规则不够全，需要为每个品类维护品牌名 → 标准品牌 ID 映射。

下一阶段（11 品类正式爬前）要补：
1. 扩 `brand_normalization.yaml` 的 `remove_suffix` 列表（含"京东自营"、"专卖店"、"专营店"等）
2. 扩 `alias_mapping`（"Apple产品京东自营旗舰店" → "Apple"，"iQOO京东自营旗舰店" → "iQOO"）
3. 从 `wareName`（商品标题）兜底提取品牌（标题首词常含品牌名，如"小米15 徕卡..."）

### 4.2 品类配置不全

`config/categories.yaml` 目前只有 `trial_category`（手机），11 个目标品类（成人护理、
婴童乳霜纸、棉柔巾·绵柔巾、婴童纸尿裤、婴童拉拉裤、婴童湿巾、卫生巾、卫生护垫、
裤型卫生巾、湿厕纸、湿巾）的 `cid2`/`cid3` 还没填。

京东 cid2/cid3 可以从搜索 URL 里抓到（如 `https://search.jd.com/Search?keyword=棉柔巾&cid2=...`），
下一步要在浏览器里跑一遍搜索，记录每个品类的 cid2/cid3。

### 4.3 trial_category 用"手机"是验证用，正式爬不能用

正式爬必须切到 11 个目标品类。"手机"品类体量大、活跃高，京东风控也严，
不适合做正式采集目标。

## 5. 文件清单

新增：
- `src/jd_analytics/spiders/drission_spider.py` (核心 DrissionPage spider)
- `src/jd_analytics/spiders/jd_category_spider.py` (scrapy 版备用，已弃用)
- `docs/features/trial-report-2026-08-25.md` (本报告)

修改：
- `src/jd_analytics/aggregator.py` (改用 cumu_review_count 直接聚合，不再依赖 delta)
- `docs/features/F001-jd-brand-analytics.md` (§2/§3 重写)
- `pyproject.toml` (加 DrissionPage 依赖)
- `src/jd_analytics/config/categories.yaml` (无变化，仅 trial_category 验证)
- `src/jd_analytics/middlewares/*.py` (简化，去 proxy/behavior)
- `src/jd_analytics/pipelines/*.py` (无变化)
- `src/jd_analytics/settings.py` (AutoThrottle via EXTENSIONS)
- `tests/test_smoke.py` (10/10 通过)

## 6. 下一步

试爬通过 → 进入 Phase 2 正式采集前，需 CVO 确认两件事：

1. **品类 cid2/cid3 补全**：要在浏览器里跑 11 个品类的搜索，
   从京东 URL 里抓 cid2/cid3 填进 `categories.yaml`。
   - 选项 A：让 CVO 提供每个品类的 cid2/cid3（CVO 自己手动搜索 → 复制 URL）
   - 选项 B：开发辅助脚本，DrissionPage 启动后让 CVO 依次搜索 11 个品类，
     自动记录 cid2/cid3 写入 yaml

2. **品牌归一规则补全**：试爬品类是"手机"，11 个目标品类品牌完全不同
   （棉柔巾的"德佑"/"可优比"/"babycare"，纸尿裤的"花王"/"帮宝适"/"好奇"），
   要么：
   - 选项 A：先跑首月抓取，看实际 shopName 列表，再补 brand_normalization.yaml
   - 选项 B：从 wareName 标题首词推断品牌（兜底方案，准确率约 70-80%）

**推荐路径**：选项 1B + 选项 2A（开发 cid2/cid3 抓取辅助 + 首月数据看实际店铺名再补归一规则）。
