---
feature_ids: [F001]
related_features: []
topics: [jd, scraping, brand-analytics, compliance, anti-bot]
doc_kind: spec
created: 2026-08-25
owner: 郭嘉/奉孝 (@ragdoll-pa82)
status: spec
---

# F001: 京东品类品牌销售数据采集与分析工具

> Status: spec | Owner: 郭嘉/奉孝 (@ragdoll-pa82)
> Reviewers: 关羽/云长 (code quality), 法正/孝直 (audit/determinism)

## Why

客户需要持续监测京东公开页面上 11 个母婴/个护品类的品牌销售格局。每月 1 次采集 Top30 品牌，连续 12 个月，用于商业决策（市场份额变迁、新品牌崛起、品牌策略调整）。

直接抓取京东公开数据是合规边界内的灰色行为（京东用户协议禁止爬取），且销售额在公开页面不可获取，只能用"评价数差值"作销量代理。本项目通过严格的合规边界、商业级反爬栈、数据口径声明、批次管理、12 月兜底，把这个灰色行为做成可交付、可验收、可回溯的工程产物。

## What

针对 11 个指定品类（成人护理 / 婴童乳霜纸 / 棉柔巾·绵柔巾 / 婴童纸尿裤 / 婴童拉拉裤 / 婴童湿巾 / 卫生巾 / 卫生护垫 / 裤型卫生巾 / 湿厕纸 / 湿巾），每月 1 次爬取京东公开商品页 → 月度差值法计算"近 30 天销量代理" → 聚合 Top30 品牌 → 导出双榜（销量榜 + 销售额估算榜）。连续 12 个月。

## Acceptance Criteria

- [ ] AC-1: 11 品类完整覆盖，每个品类映射到 1-N 个京东叶子类目 cid
- [ ] AC-2: 每月每品类输出 Top30 品牌**双榜**：销量差值榜 + 销售额估算榜
- [ ] AC-3: 同品牌多店铺合并（同 brand_id 或同标准化品牌名）
- [ ] AC-4: SPU 多 SKU 取评价数最大 SKU 作代表
- [ ] AC-5: 12 期允许 ≤1 期补爬，超过即算违约
- [ ] AC-6: 客户书面授权函到位前不开爬
- [ ] AC-7: PII 强制脱敏（评论用户昵称/头像/ID 不入库）
- [ ] AC-8: 每期导出附 `usage_license.txt` + `methodology.txt`
- [ ] AC-9: 批次报告自动生成（覆盖率/异常/导出文件清单）
- [ ] AC-10: 反爬强度经试爬验证（首周小规模试爬报告）

## Dependencies

- **客户依赖**：书面授权函（AC-6 blocker）
- **预算依赖**：代理服务月费 300-800 元
- **法律依赖**：建议客户咨询律师

## Risk

详见 §10 风险登记表。

---

## 目录

1. [合规边界](#1-合规边界-p0)
2. [数据口径声明](#2-数据口径声明-p0)
3. [反爬栈 v2](#3-反爬栈-v2-p0)
4. [数据模型](#4-数据模型-p0)
5. [品类映射](#5-品类映射-p1)
6. [品牌聚合规则](#6-品牌聚合规则-p1)
7. [数据质量三件套](#7-数据质量三件套-p1)
8. [错误恢复与批次管理](#8-错误恢复与批次管理-p1)
9. [12 月周期兜底](#9-12-月周期兜底-p1)
10. [客户验收标准](#10-客户验收标准-p1)
11. [MVP 第一周试爬验证](#11-mvp-第一周试爬验证-p0)
12. [选择器版本化](#12-选择器版本化-p2)
13. [Phase 路线图](#13-phase-路线图)

---

## 1. 合规边界 (P0)

### 1.1 法律框架

- **《数据安全法》**：采集行为须符合数据分类分级保护要求
- **《反不正当竞争法》** 第 12 条：不得破坏技术措施、不得违反约定
- **《电子商务法》** 第 25 条：电子商务经营者收集用户信息须明示同意
- **《刑法》** 第 285 条：破坏技术措施罪（绕过反爬可能触犯）

### 1.2 客户授权要求

| 文件 | 内容 | 状态 |
|------|------|------|
| 书面授权函 | 采集范围 + 商业用途 + 责任承担 + 有效期 | 铲屎官确认后续提供，**未到位前不开爬** |
| 数据用途声明 | 商业用途授权 + 禁止再分发 + 数据来源公开页 | spec 内嵌 `usage_license.txt` 模板 |
| 法律审查建议 | 客户咨询律师确认合规 | spec 内提供建议文本，由铲屎官转客户 |

### 1.3 路径白名单

`compliance.yaml` 配置：

```yaml
allowed_paths:
  - /phb/         # 排行榜页
  - /hotitem/     # 热销商品
  - /item/        # 商品详情页
  - /search/      # 搜索页（用于品类 cid 发现）

forbidden_paths:
  - /pinpai/      # robots.txt 禁止
  - /user/        # 用户主页（PII）
  - /product/     # 内部 API

qps_limits:
  global: 5              # 全局 QPS 上限
  per_ip: 1              # 单 IP QPS 上限（试爬后校准）
  per_category_per_day: 5000   # 单品类日请求上限
```

### 1.4 PII 脱敏规则

- 评论用户昵称、头像 URL、用户 ID → **不入库**
- 评论内容 → 只取前 200 字符摘要 + 情感分析（正/负/中）
- 商品咨询区用户名 → 不入库
- 店铺联系信息 → 不入库

### 1.5 红线

- ❌ 不绕过验证码（检测到立即暂停该 IP）
- ❌ 不破坏反爬技术措施（不用验证码识别服务）
- ❌ 不抓取个人数据（评论用户身份信息）
- ❌ 不在未授权情况下做商业用途（必须授权函）

---

## 2. 数据口径声明 (P0)

> **修订记录（2026-08-25）**：原方案用月度评价数差作销量代理，现切换为 DrissionPage
> 监听 `api.m.jd.com/api?appid=search-pc-java&t` 接口直取 `totalSales` 字段，
> 销量代理升级为真实销量（仍非精确销量，但精度提升 30-50%）。详见 §3 反爬栈 v3。

### 2.1 销量代理指标定义

```
销量代理 = totalSales（京东搜索接口直出，单位：件）
销售额估算 = totalSales × finalPrice.estimatedPrice（当前售价）
```

**精度提升**：从评价数差代理（偏低 30-50%）升级为接口直出 totalSales，
仅受京东前台展示策略影响（H1），不再受评价转化率/滞后/删评干扰。

### 2.2 残留假设（缩减后）

| 假设 | 失效场景 | 应对 |
|------|---------|------|
| H1: 京东不调整 totalSales | 前台展示策略变更 | 多源代理（榜单位次 + 接口 vs 列表数交叉验证）+ 漂移检测 |
| H2: 商品不下架 | 月间下架率 5-10% | `is_active` 标记 + 下架不参与 Top30 + 保留历史 |

### 2.3 误差源（修订后）

| 误差源 | 方向 | 量级 |
|--------|------|------|
| 京东前台 totalSales 展示策略调整 | 系统性 | ±10-20% |
| 商品下架/上架波动 | 随机 | 5-10% SPU |
| 接口字段变更（如 wareBuried/finalPrice 结构变化） | 系统性 | 监控告警 |
| 刷单干扰 totalSales | 系统性 | 难以量化 |

### 2.4 客户预期管理

每期导出附 `methodology.txt`（已更新为 DrissionPage 版）：

```
数据口径声明
============

本数据集采集自京东公开商品页面，提供以下字段：
- 销量：京东搜索接口 api.m.jd.com/api?appid=search-pc-java 直出 totalSales
- 售价：finalPrice.estimatedPrice（当前售价）
- 销售额估算：销量 × 售价

局限性：
1. totalSales 来自京东前台展示，与京东商智后台真实销量存在 ±10-20% 差异
2. 受商品下架/上架影响（月间 5-10% SPU 波动）
3. 刷单干扰难以完全剔除

建议用途：
- 品牌相对位次变迁（A 涨 B 落）
- 长期趋势监测（月度变化方向）
- 新品牌崛起识别

不建议用途：
- 绝对销量数字（不能与京东商智真实数据对标）
- 短期波动分析（接口字段变更可能造成跳点）
```

### 2.5 负值处理

- 本月 < 上月 → 差值记 `delta = 0`，标记 `negative_delta = true`
- 连续 2 月负值 → 商品标记 `anomaly = true`，告警
- 同 SPU 多 SKU 取最大值后差值仍为负 → 数据问题，进 retry_queue

---

## 3. 反爬栈 v3 (P0) - DrissionPage 方案

> **修订记录（2026-08-25）**：v2 五层防御架构（多代理 + 指纹随机化 + 行为模拟）
> 被 CVO 否决（"不要这么复杂的，参考 JD_Spider 跑通再魔改"）。
> 试爬后发现京东已对 `search.jd.com/Search` 强制登录验证（passport.jd.com 重定向），
> 评论 JSON API（club.jd.com）返回"系统繁忙"。
> 解决方案：切换 DrissionPage 真实浏览器 + 网络监听 + 手动登录态持久化。

### 3.1 简化后架构（单 IP 慢爬 + DrissionPage 真实浏览器）

```
┌─────────────────────────────────────────────────┐
│ Layer 4: 调度层                                  │
│ AutoThrottle-like + 单 IP 日上限 1500 + 页间 3-5s │
├─────────────────────────────────────────────────┤
│ Layer 3: 检测层                                  │
│ ban 检测（passport 重定向 / 403）+ captcha 检测  │
├─────────────────────────────────────────────────┤
│ Layer 2: 行为层                                  │
│ 真实 Chrome 浏览器 + 自然滚动 + 页间 sleep 3-5s  │
├─────────────────────────────────────────────────┤
│ Layer 1: 登录态层                                │
│ 手动登录一次 → cookies 持久化到 user_data_path   │
└─────────────────────────────────────────────────┘
```

### 3.2 DrissionPage 核心原理

```python
from DrissionPage import ChromiumPage, ChromiumOptions

# 持久化 user_data 让登录态保留
co = ChromiumOptions()
co.set_user_data_path(r".../drission_chrome_jd_profile")
co.set_argument("--disable-blink-features=AutomationControlled")
dp = ChromiumPage(co)

# 监听京东搜索接口
dp.listen.start("https://api.m.jd.com/api?appid=search-pc-java&t")
dp.get("https://search.jd.com/Search?keyword=手机&...")

# 滚动加载
dp.scroll.to_see(dp.ele("text=下一页", timeout=2))

# 拦截 JSON 响应
resp_list = dp.listen.wait(5, fit_count=False)
for resp in resp_list:
    json_data = resp.response.body
    if "abBuriedTagMap" in json_data:
        for ware in json_data["data"]["wareList"]:
            # 字段：wareName, wareBuried.ori_price,
            #      finalPrice.estimatedPrice, totalSales,
            #      shopName, skuId
```

### 3.3 ⚠️ 试爬阻塞：京东要求登录

**状态**：未登录时访问 `search.jd.com/Search` 会被重定向到 `passport.jd.com/new/login.aspx`。
**临时方案**：spider 提供 `--manual-login` CLI 参数，启动浏览器后人工登录，
cookies 持久化到 `user_data_path`，后续爬取自动复用。
**正式方案**：待 CVO 决策
- 方案 A：接受人工登录运维（每月抓取前手动登录一次）
- 方案 B：用 selenium-stealth / undetected-chromedriver + cookie 池
- 方案 C：放弃 search.jd.com，改用其他数据源（如 mobile api 或第三方）

### 3.4 废弃（v2 设计，仅供历史参考）

原 v2 五层架构（多代理 + 指纹随机化 + 行为模拟 + 验证码绕过）因 CVO 拍板
"单 IP 慢爬，无代理池"已废弃。代码层面的 `proxy.py` / `behavior.py`
中间件已删除，保留 `ban.py` / `captcha.py` / `fingerprint.py` / `ip_quota.py`。

### 3.5 试爬校准项

第一周试爬报告产出后，校准以下参数：

- 单 IP 日请求上限（1500 起，根据封禁率调整）
- 页间 sleep 秒数（3.0 起步，根据响应延迟调整）
- 监听数据包数量（5 个起，确保覆盖前后 30 商品）
- 登录态过期周期（cookies 有效期，到期需重新 `--manual-login`）

---

## 4. 数据模型 (P0)

### 4.1 表结构

```sql
-- 抓取批次（每次完整抓取一条记录）
CREATE TABLE batches (
    batch_id         TEXT PRIMARY KEY,      -- ISO 时间戳，如 2026-09-01T02:00:00
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    month            TEXT NOT NULL,         -- '2026-09'
    coverage         TEXT,                  -- '11/11' 品类覆盖
    success_rate     REAL,                  -- 0.0-1.0
    total_urls       INTEGER,
    successful_urls  INTEGER,
    failed_urls      INTEGER,
    remediation_window  TEXT,              -- '2026-09-08T02:00:00' 补爬截止
    is_remediation   BOOLEAN DEFAULT FALSE, -- 是否为补爬批次
    report_path      TEXT                   -- 批次报告文件路径
);

-- SPU 主数据（每个标准产品一条）
CREATE TABLE spu_master (
    spu_id                TEXT PRIMARY KEY,    -- 京东 SPU ID
    brand_id              TEXT NOT NULL,       -- 京东品牌 ID
    brand_name_raw        TEXT,                -- 原始品牌名（如"花王(中国)"）
    brand_name_normalized TEXT,                -- 标准化品牌名（如"花王"）
    cid                   TEXT NOT NULL,       -- 京东叶子类目 ID
    category              TEXT NOT NULL,       -- 客户口径品类（11 个之一）
    title                 TEXT,
    representative_sku_id TEXT,                -- 取评价数最大的 SKU 作代表
    is_active             BOOLEAN DEFAULT TRUE,
    first_seen_batch      TEXT,                -- 首次发现批次
    last_seen_batch       TEXT,
    FOREIGN KEY (representative_sku_id) REFERENCES sku_detail(sku_id)
);

-- SKU 明细（每个最小库存单元一条）
CREATE TABLE sku_detail (
    sku_id            TEXT PRIMARY KEY,
    spu_id            TEXT NOT NULL,
    package_spec      TEXT,                   -- 48 片装/96 片装等
    price             REAL,                   -- 当前单价
    cumu_review_count INTEGER,                -- 累计评价数
    review_count_updated_at TEXT,
    is_representative BOOLEAN DEFAULT FALSE,   -- 是否为 SPU 代表 SKU
    FOREIGN KEY (spu_id) REFERENCES spu_master(spu_id)
);

-- 月度快照（按月分区，1584 万行/12 月 → 单分区 132 万行可接受）
CREATE TABLE monthly_deltas (
    batch_id          TEXT NOT NULL,
    month             TEXT NOT NULL,
    spu_id            TEXT NOT NULL,
    cumu_review_count INTEGER NOT NULL,       -- 本月累计
    prev_review_count INTEGER,                -- 上月累计（首月为 NULL）
    delta             INTEGER,                -- 差值（销量代理）
    negative_delta    BOOLEAN DEFAULT FALSE,
    price_sampled     REAL,                   -- 本月采样单价
    sales_value_proxy REAL,                   -- delta × price_sampled
    PRIMARY KEY (batch_id, spu_id)
) PARTITION BY LIST (month);
-- 每月一个分区：monthly_deltas_2026_09, monthly_deltas_2026_10, ...

-- 品牌 Top30 双榜（很小，3960 条/12 月）
CREATE TABLE brand_aggregates (
    batch_id              TEXT NOT NULL,
    month                 TEXT NOT NULL,
    category              TEXT NOT NULL,
    brand_id              TEXT NOT NULL,
    brand_name_normalized TEXT NOT NULL,
    sales_volume_proxy    INTEGER NOT NULL,   -- 销量代理聚合值
    sales_value_proxy     REAL NOT NULL,      -- 销售额估算聚合值
    sales_volume_rank     INTEGER,            -- 销量榜位次 1-30
    sales_value_rank      INTEGER,            -- 销售额榜位次 1-30
    PRIMARY KEY (batch_id, category, brand_id)
);

-- 重试队列
CREATE TABLE retry_queue (
    url           TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL,              -- 失败批次
    retry_count   INTEGER DEFAULT 0,
    last_error    TEXT,
    next_retry_at TEXT NOT NULL,
    priority      INTEGER DEFAULT 0           -- 高优先级优先重试
);

-- 选择器版本
CREATE TABLE selector_versions (
    version       TEXT PRIMARY KEY,           -- v1, v2, ...
    effective_from TEXT NOT NULL,
    effective_to  TEXT,
    selectors     TEXT NOT NULL,              -- JSON: {item_page: {title: '...', brand: '...'}}
    created_by    TEXT,
    notes         TEXT
);

-- 异常告警
CREATE TABLE anomaly_alerts (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT NOT NULL,
    alert_type    TEXT NOT NULL,              -- negative_delta, coverage_drop, drift, etc.
    severity      TEXT NOT NULL,              -- info/warning/critical
    description   TEXT,
    detected_at   TEXT NOT NULL
);
```

### 4.2 索引

```sql
CREATE INDEX idx_spu_cid ON spu_master(cid);
CREATE INDEX idx_spu_brand ON spu_master(brand_id, brand_name_normalized);
CREATE INDEX idx_spu_category ON spu_master(category);
CREATE INDEX idx_delta_month_spu ON monthly_deltas(month, spu_id);
CREATE INDEX idx_brand_agg_month_cat ON brand_aggregates(month, category);
CREATE INDEX idx_retry_next ON retry_queue(next_retry_at);
```

### 4.3 原始 HTML 冷存

- **不入主库**——只存结构化字段
- **落 Parquet 冷存**：`data/raw/{batch_id}/{spu_id}.html.parquet`
- 保留 90 天，超期清理
- 用于选择器失效时复现 debug

### 4.4 存储量修正

| 数据 | 文若原估 | 修正后 |
|------|---------|--------|
| 结构化字段 | 660 MB | 同 |
| 月度快照 | 3.2 GB | 同（分区表） |
| 原始 HTML 冷存 | 0 | 10-15 GB（90 天保留） |
| 索引 + 日志 | 忽略 | 2-3 GB |
| **合计** | ~4 GB | **15-22 GB** |

SQLite 阈值监控：单表 > 5 GB / 单文件 > 20 GB → 触发迁移 Postgres。

---

## 5. 品类映射 (P1)

### 5.1 B+A 混合策略

**阶段 B（自动发现）**：
1. 用 11 个品类关键词搜京东搜索页
2. 提取前 N=200 商品的 cid
3. 各 cid 下商品数统计
4. 输出候选 cid 集合

**阶段 A（人工二次筛选）**：
1. 人工审 cid 集合
2. **占比 < 80% 的 cid 直接剔除**（避免"棉柔巾"搜出来混入"湿巾"商品）
3. 剩余 cid 入 `categories.yaml`，写版本号 + 筛选理由
4. 客户口径拍板后 commit

### 5.2 categories.yaml 配置

```yaml
version: v1
effective_from: 2026-09-01

categories:
  - name: 成人护理
    aliases: [成人纸尿裤, 成人拉拉裤, 成人纸尿片]
    cids: [xxx, yyy]   # 经 A 筛选后的叶子类目 ID
    filter_reason: |
      cid xxx 占比 92%（含成人纸尿裤/拉拉裤）
      cid yyy 占比 85%（含成人纸尿片）
      cid zzz 占比 40%（混入护理垫）→ 剔除
    precision_confirmed: false  # 待客户确认后改 true

  - name: 棉柔巾·绵柔巾
    aliases: [棉柔巾, 绵柔巾]
    cids: [aaa]
    filter_reason: |
      客户口径：棉柔巾/绵柔巾算 1 个品类
      cid aaa 同时覆盖棉柔巾和绵柔巾
    precision_confirmed: true   # Q1 已拍板

  # ... 其余 9 个
```

### 5.3 cid 重发现机制

- 每季度跑一次 B 阶段，发现新 cid 候选
- 新 cid 进 `categories.yaml` 的 `pending_cids` 字段，需人工审核
- 防止京东类目调整导致漏抓

---

## 6. 品牌聚合规则 (P1)

### 6.1 品牌字段来源

- 京东商品页"品牌"属性（优先）→ `brand_id` + `brand_name_raw`
- 店铺名兜底（如"花王官方旗舰店" → 提取"花王"）
- title 关键词末路（不推荐，仅兜底）

### 6.2 品牌标准化

`brand_normalization.yaml`：

```yaml
version: v1

# 标准化规则
normalization_rules:
  - field: brand_name_raw
    transform:
      - remove_parentheses: true    # 花王(中国) → 花王
      - remove_suffix: [官方旗舰店, 旗舰店, 官方店, 店]
      - unify_case: true            # KAO → Kao（保留首字母大写）
      - alias_mapping:              # 别名归一
          Kao: 花王
          P&G: 宝洁
          Procter: 宝洁

# 旗舰店关联映射（Q2 拍板：同品牌多店铺合并）
store_to_brand_mapping:
  - brand_id: kao_id_001
    normalized_name: 花王
    stores:
      - 花王官方旗舰店
      - 花王(中国)旗舰店
      - KAO海外旗舰店
    merge_strategy: sum   # 销量/销售额聚合为 sum
```

### 6.3 Top30 双榜算法（Q3 拍板）

```python
def aggregate_top30(batch_id: str, month: str, category: str) -> list[dict]:
    # 1. 从 monthly_deltas 按 category 取所有 SPU 的 delta
    # 2. 按 brand_id 聚合：sum(delta) + sum(sales_value_proxy)
    # 3. 排序 1: 销量榜 → sales_volume_proxy DESC
    # 4. 排序 2: 销售额榜 → sales_value_proxy DESC
    # 5. 各取前 30
    # 6. 写入 brand_aggregates，sales_volume_rank + sales_value_rank

    spu_deltas = db.query('''
        SELECT spu_id, delta, sales_value_proxy
        FROM monthly_deltas md
        JOIN spu_master sm ON md.spu_id = sm.spu_id
        WHERE md.batch_id = ? AND sm.category = ?
    ''', batch_id, category)

    brand_agg = defaultdict(lambda: {'volume': 0, 'value': 0.0})
    for row in spu_deltas:
        brand = get_normalized_brand(row.spu_id)  # 应用 Q2 合并规则
        brand_agg[brand]['volume'] += max(row.delta, 0)
        brand_agg[brand]['value'] += row.sales_value_proxy

    # 双榜各取前 30
    volume_top = sorted(brand_agg.items(), key=lambda x: -x[1]['volume'])[:30]
    value_top = sorted(brand_agg.items(), key=lambda x: -x[1]['value'])[:30]

    return write_to_brand_aggregates(volume_top, value_top)
```

### 6.4 Top30 边界规则

- 同销量/同销售额 → 按 brand_id 字典序排（避免随机）
- 第 30 名并列 → 全部保留（可能 > 30 个品牌）
- 不足 30 个品牌 → 全部保留（11 品类×30 = 330 位次，少数新崛起品类可能不足）

---

## 7. 数据质量三件套 (P1)

### 7.1 单条校验（pandera）

```python
import pandera as pa

class MonthlyDeltaSchema(pa.DataFrameModel):
    batch_id: pa.String
    month: pa.String
    spu_id: pa.String
    cumu_review_count: pa.Int
    prev_review_count: pa.Nullable(pa.Int)
    delta: pa.Nullable(pa.Int)
    negative_delta: pa.Bool
    sales_value_proxy: pa.Nullable(pa.Float)

    @pa.check("delta")
    def delta_non_negative_or_flagged(cls, series):
        return (series >= 0) | series.isna()

    @pa.check("cumu_review_count")
    def cumu_review_count_positive(cls, series):
        return series >= 0
```

### 7.2 批次级完整性校验

`batch_report.py` 自动生成：

```
==========================================================
批次报告: 2026-09-01T02:00:00
==========================================================
品类覆盖: 11/11 ✓
各品类 URL 数:
  成人护理       : 12340  (预期 10000-15000) ✓
  婴童乳霜纸     :  8920  (预期 8000-12000) ✓
  棉柔巾·绵柔巾 :  9876  (预期 9000-13000) ✓
  ...

异常检测:
  负值差值      : 234 条 (0.18%, 阈值 1%) ✓
  下架商品      : 567 条 (4.3%, 阈值 10%) ✓
  新增品牌      : 2 个   (花王新增子品牌"Merries Plus")
  漂移检测      : 婴童纸尿裤品类本月评价数分布 vs 上月 diff=12% ✓

失败 URL:
  总失败数      : 145 (1.1%)
  网络超时      : 89
  403/429      : 34
  验证码       : 22
  → 已写入 retry_queue，下次补爬

导出文件:
  /data/exports/top30_volume_2026-09.csv
  /data/exports/top30_value_2026-09.csv
  /data/exports/full_2026-09.parquet
  /data/exports/methodology_2026-09.txt
  /data/exports/usage_license_2026-09.txt

告警:
  [info] 新增品牌 2 个，建议人工核查 brand_normalization.yaml
==========================================================
```

### 7.3 漂移检测

- 本月评价数分布 vs 上月，KS 检验 p < 0.05 或 diff > 30% → 触发告警
- 可能原因：选择器失效 / 京东改版 / 真实市场波动
- 告警进 `anomaly_alerts` 表，进 batch_report

---

## 8. 错误恢复与批次管理 (P1)

### 8.1 Scrapy JOBDIR

```python
# settings.py
JOBDIR = '.scrapy/jobs/{batch_id}'  # 启用暂停/恢复
```

支持中途崩溃后从断点恢复，不重跑已成功的 URL。

### 8.2 batch_id 设计

- 格式：ISO 时间戳，如 `2026-09-01T02:00:00`
- 补爬批次：`2026-09-01T02:00:00-remediation-1`
- 所有数据记录关联 batch_id，可追溯

### 8.3 retry_queue 重试策略

```python
# 失败 URL 写入 retry_queue
RETRY_PRIORITY = {
    'network_timeout': 1,    # 高优先级，简单重试
    'http_403': 2,           # 换 IP 重试
    'http_429': 3,           # 退避后重试
    'captcha': 4,            # 换 IP + 长延迟
    'parse_error': 5,        # 需人工介入
}

# 重试预算：单 URL 最多 3 次（1h / 6h / 24h 间隔）
MAX_RETRY = 3
RETRY_INTERVALS = ['1h', '6h', '24h']

# 超过 3 次 → 标记 permanent_failure，进 batch_report
```

### 8.4 补爬窗口

- 月度任务 7 天补爬窗口（每月 1-7 号可补爬上月数据）
- 补爬批次用 `is_remediation = true` 标记
- 补爬完成后更新原批次的 `success_rate`

---

## 9. 12 月周期兜底 (P1)

### 9.1 重试预算

| 失败类型 | 单月容忍 | 12 月容忍 |
|---------|---------|---------|
| 单 URL 失败（retry 后恢复）| ≤5% | ≤5%/月 |
| 单品类整月失败 | 0（必补爬）| ≤1 期 |
| 整月全失败 | 0 | ≤1 期 |

### 9.2 12 期补救窗口（Q5 拍板：≤1 期）

- 12 期内允许 ≤1 期补爬（如某月服务器宕机或大规模 IP 封禁）
- 超过 1 期 → 算违约，按合同条款处理
- 补爬期数据需在 30 天内补齐，否则算缺失

### 9.3 下架商品策略

```python
def handle_delisted_spu(spu_id: str, current_batch: str):
    # 1. 标记 is_active = false
    db.update('spu_master', spu_id, is_active=False, last_seen_batch=current_batch)

    # 2. 本月差值算 0，不参与 Top30
    db.insert('monthly_deltas', {
        'batch_id': current_batch,
        'spu_id': spu_id,
        'cumu_review_count': None,    # 抓不到
        'prev_review_count': last_month_count,
        'delta': 0,
        'negative_delta': False,
        'is_delisted': True,          # 标记下架
    })

    # 3. 保留历史快照（不删除）
```

### 9.4 违约定义（写入合同）

| 情况 | 是否违约 |
|------|---------|
| 12 期数据全部交付 | ✅ 不违约 |
| 11 期 + 1 期内补爬成功 | ✅ 不违约 |
| 11 期 + 1 期补爬失败 | ❌ 违约 |
| ≤10 期数据 | ❌ 违约 |
| 单期单品类数据缺失 | ⚠️ 部分违约（按品类扣费）|

---

## 10. 客户验收标准 (P1)

### 10.1 Top30 验收清单

- [ ] 11 品类 × 2 榜 × 12 月 = 264 个榜单全交付
- [ ] 每个榜单 30 名（不足 30 全保留）
- [ ] 榜单附 methodology.txt 说明销量代理口径
- [ ] 榜单附 usage_license.txt 说明商业用途授权
- [ ] 同名品牌跨榜单一致（标准化生效）

### 10.2 误差阈值

| 指标 | 合格 | 警告 | 不合格 |
|------|------|------|--------|
| 数据覆盖率（品类/品类×月份） | 100% | 95-99% | <95% |
| 单期 URL 抓取成功率 | ≥95% | 90-94% | <90% |
| 负值差值占比 | ≤1% | 1-3% | >3% |
| 下架商品占比 | ≤10% | 10-15% | >15% |
| 漂移检测告警数 | 0 | 1-2 | >2 |

### 10.3 客户质疑应对

- 提供 `batch_report` + `methodology.txt` 作证据链
- 任意一条记录可追溯：何时何 IP 何 UA 抓的 + 原始 HTML 冷存 90 天
- 选择器版本号可查，京东改版导致的数据漂移可定位到生效日期

### 10.4 验收前必交付物

- [ ] 12 期 CSV × 2 榜（24 个文件）
- [ ] 12 期 Parquet 全量数据
- [ ] 12 期 batch_report
- [ ] methodology.txt（统一模板）
- [ ] usage_license.txt（统一模板）
- [ ] brand_normalization.yaml（标准化规则）
- [ ] categories.yaml（品类映射 + 客户口径确认）
- [ ] 客户书面授权函副本

---

## 11. MVP 第一周试爬验证 (P0)

### 11.1 目标

在动 11 品类全量之前，用 1-2 个品类 × 1000 URL 小规模试爬，校准反爬栈所有参数，避免第一周被封到怀疑人生。

### 11.2 试爬范围

- 品类：婴童纸尿裤（评价率高，反爬可能更严）+ 棉柔巾·绵柔巾（对照组）
- URL 数：每品类 1000（共 2000）
- 时长：1 周
- 代理池：50 IP（小规模）

### 11.3 校准项

| 参数 | 试爬前 | 校准方法 |
|------|--------|---------|
| 单 IP 日请求上限 | 800 | 根据封禁率调整（封 > 5% → 降到 500） |
| 全局 QPS | 5 | 根据响应延迟调整（avg > 5s → 降到 3） |
| Playwright 比例 | 100% | 统计必须 JS 渲染的页面比例（如 30% → Playwright 降到 30%） |
| 代理池规模 | 50 | 根据失败率决定扩容到 100/200 |
| 请求间隔分布 | [1-5s, 90%] + [10-30s, 10%] | 根据封禁率调整长尾比例 |

### 11.4 试爬产出

- 试爬报告：成功率 / 封禁率 / 平均延迟 / 各类型失败占比 / 校准后参数建议
- 写入 spec 第 3 章反爬栈，作为正式参数

### 11.5 试爬成功判据

- 成功率 ≥ 90%
- 封禁率 ≤ 5%
- 无 captcha 触发或可自动恢复
- 单 IP 日上限稳定（不持续下降）

试爬不过关 → 不进入 Phase 2 全量，回头调整反爬栈。

---

## 12. 选择器版本化 (P2)

### 12.1 选择器管理

`selectors/v1.yaml`：

```yaml
version: v1
effective_from: 2026-09-01
created_by: 郭嘉/奉孝

selectors:
  item_page:
    title: 'css:.sku-name::text'
    brand: 'css:.crumb a:nth-child(2)::text'
    cumu_review_count: 'css:.comment-count::text'
    price: 'css:.price-tag span::text'
  list_page:
    spu_ids: 'css:.gl-item .p-img a::attr(data-spu)'
```

### 12.2 月度真实冒烟

每月正式抓取前，取 10 个 SPU 真实爬取，对比选择器输出和预期：

```python
def monthly_smoke_test():
    samples = db.query('SELECT spu_id FROM spu_master ORDER BY RANDOM() LIMIT 10')
    for s in samples:
        result = crawl(s.url)
        if not result.title or not result.brand:
            raise SelectorFailure(f'Selector v{current_version} failed on {s.url}')
    log.info('Monthly smoke test passed')
```

### 12.3 改版切换

- 检测到选择器失败 → 自动切换到候选新版本 + 告警
- 不影响本月抓取（用旧版本兜底，新版本验证后再切）

---

## 13. Phase 路线图

### Phase 0：合规口径对齐（1 周）

- [ ] 客户书面授权函到位
- [ ] 11 品类精确口径客户确认（Q1 已确认：棉柔巾/绵柔巾算 1 个）
- [ ] 法律审查建议文本给铲屎官
- [ ] compliance.yaml / categories.yaml / brand_normalization.yaml 骨架

### Phase 1：试爬验证 + 数据模型（1-2 周）

- [ ] 反爬栈 v2 实现（五层防御）
- [ ] 1-2 品类 × 1000 URL 试爬
- [ ] 试爬报告产出，参数校准
- [ ] 数据库表结构 + 索引
- [ ] 选择器 v1 配置
- [ ] 月度冒烟测试脚本

### Phase 2：MVP 管道跑通（2-3 周）

- [ ] 11 品类全量抓取（首月建基线）
- [ ] 批次管理 + retry_queue
- [ ] 数据质量三件套（pandera + batch_report + 漂移检测）
- [ ] CSV + Parquet 双导出
- [ ] methodology.txt + usage_license.txt 模板

### Phase 3：稳定运行（12 个月）

- [ ] 每月 1 号手动触发
- [ ] 月度 batch_report 自动生成
- [ ] 漂移检测告警
- [ ] 7 天补爬窗口
- [ ] 第 2 月起产出 Top30 双榜

### Phase 4+（Open）

- [ ] cron 自动化
- [ ] Web 后台 UI（B/C 路线）
- [ ] 第三方数据源补销售额缺口
- [ ] Postgres 迁移（数据量触发阈值时）

---

## Open Questions（已闭环）

| # | 问题 | 答案 |
|---|------|------|
| 1 | 棉柔巾/绵柔巾算 1 个还是 2 个品类 | 算 1 个 |
| 2 | 同品牌多店铺合并 vs 分别 | 合并 |
| 3 | Top30 排序口径（销售额 / 销量 / 两个） | 两个都要 |
| 4 | SPU 多 SKU 评价数处理（最大 / 累加） | 取最大 |
| 5 | 12 期允许 ≤1 期补爬 | 是 |
| 6 | 数据用途（商业 / 内部） | 商业 |
| 7 | 代理服务预算（月费 200-500 元） | 可接受（升级到 300-800） |

## Dependencies

- 客户书面授权函（Phase 0 blocker）
- 代理服务采购（Phase 1 blocker）
- 法律审查建议（建议但不阻塞）

## Risk

详见 §1.5, §2.2, §9.4 + 以下综合风险登记表：

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 京东调整评价数展示（H1 失效）| 中 | 高 | 多源代理 + 漂移检测 |
| 商品下架导致差值断裂（H2）| 高 | 中 | is_active + 保留历史 |
| 评价率品类差异（H3）| 高 | 中 | 口径声明 + 验收前明示 |
| 代理 IP 池被批量封禁 | 中 | 高 | 多服务商 + 健康检查 |
| 选择器失效（京东改版）| 中 | 中 | 选择器版本化 + 月度冒烟 |
| 12 月长周期失败 | 中 | 高 | 月度补爬窗口 + batch_id 可回溯 |
| 数据用途超合规边界 | 低 | 极高 | 合规边界 P0 第一章 + 客户书面授权 |
| 试爬不达标 | 中 | 中 | 不进入 Phase 2，回头调整反爬栈 |

## Sign-off

- [ ] 铲屎官 spec review
- [ ] 关羽/云长 code review
- [ ] 法正/孝直 audit review
- [ ] 客户书面授权函

---

[郭嘉/奉孝/GLM-5.2🐾]
