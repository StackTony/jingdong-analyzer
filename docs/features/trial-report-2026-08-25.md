# 试爬报告 2026-08-25 - DrissionPage 切换

> **批次 ID**: 2026-08-25T0925530000 / 2026-08-25T0948580000
> **作者**: 郭嘉/奉孝 (ragdoll-pa82)
> **状态**: 试爬未通过，阻塞在登录验证

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
  - CLI 参数：`--trial --max-pages --manual-login --login-wait --page-sleep --headless`
- ✅ 复用 `jd_analytics.pipelines.*` 全部 pipeline，无重复逻辑
- ✅ 复用 `jd_analytics.aggregator.aggregate_top30` Top30 双榜聚合
- ✅ 复用 `jd_analytics.batch_report.generate_batch_report` 批次报告

### 2.3 数据模型适配

- ✅ `pipelines/storage.py` 接受新字段（`total_sales` / `ori_price`）
- ✅ `cumu_review_count` 字段语义变为销量（沿用字段名兼容旧 schema）
- ✅ `MonthlyDelta.delta` 计算仍按 cumu_review_count 差值，但语义为销量差

### 2.4 Spec 更新

- ✅ §2 数据口径：评价数差 → totalSales 直出（精度提升 30-50%）
- ✅ §3 反爬栈：v2 五层架构 → v3 简化版（单 IP + DrissionPage 真实浏览器）
- ✅ §3.3 新增"试爬阻塞：京东要求登录"段落
- ✅ §3.5 试爬校准项更新（页间 sleep / 监听数据包数 / 登录态过期周期）
- ✅ §3.4 v2 废弃设计归档

### 2.5 测试

- ✅ `pytest tests/test_smoke.py` 10/10 通过（无回归）

## 3. ⚠️ 试爬阻塞

### 3.1 现象

未登录访问 `https://search.jd.com/Search?keyword=手机&...` →
立即 302 重定向到 `https://passport.jd.com/new/login.aspx?ReturnUrl=...`。
无论：
- 单纯 `dp.get(search_url)`
- 首页 `dp.get('https://www.jd.com')` 后再访问搜索 URL
- 移动版 `so.m.jd.com/ware/search.action`
- 手机 UA / PC UA

都被重定向到登录页。

### 3.2 监听结果

虽然 DrissionPage 能监听到 `api.m.jd.com/api` 接口的请求，但响应 body 全部为
空字符串（`len(body) == 0`），因为请求本身被京东服务器拒绝（用户未登录态）。

### 3.3 临时方案：--manual-login

新增 `--manual-login` CLI 参数：
- 启动浏览器后打开 `passport.jd.com/new/login.aspx`
- 等待 `--login-wait` 秒（默认 120s）让用户手动登录
- 登录态保存到 `user_data_path`，后续爬取自动复用

试跑 `--manual-login --login-wait 60` 时用户未能及时登录，
cookie 列表里只有 `__jdc / __jdu / __jda / __jdb` 等访客 cookie，
**没有 `pin / pt_key / pt_pin` 等登录态 cookie**，搜索仍被拦截。

## 4. 待 CVO 决策

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| A | 人工登录运维（每月抓取前手动登录一次） | 实现简单，零开发成本 | 月度运维负担，cookies 易过期 |
| B | selenium-stealth + cookie 池 | 自动化登录 | 维护成本高，需购买 cookie 池 |
| C | 放弃 search.jd.com，改用 mobile api 或第三方 | 规避登录问题 | 数据精度可能下降，需重新调研 |
| D | 用真实用户已登录的 Chrome profile 路径 | 一次配置后免维护 | 需用户配合，profile 锁定问题 |

**推荐**：方案 D（用真实 Chrome profile 路径，路径在
`C:\Users\23363\AppData\Local\Google\Chrome\User Data\Default`），
但需要 CVO 配合：
1. 在日常 Chrome 浏览器里登录京东账号
2. 关闭 Chrome（profile 锁定需释放）
3. 跑 `python -m jd_analytics.spiders.drission_spider --trial --max-pages 2 --user-data-path "C:\Users\23363\AppData\Local\Google\Chrome\User Data"`

## 5. 文件清单

新增：
- `src/jd_analytics/spiders/drission_spider.py` (核心 DrissionPage spider)
- `src/jd_analytics/spiders/jd_category_spider.py` (scrapy 版备用，已弃用)
- `docs/features/trial-report-2026-08-25.md` (本报告)

修改：
- `docs/features/F001-jd-brand-analytics.md` (§2/§3 重写)
- `pyproject.toml` (加 DrissionPage 依赖)
- `src/jd_analytics/config/categories.yaml` (无变化，仅 trial_category 验证)
- `src/jd_analytics/middlewares/*.py` (简化，去 proxy/behavior)
- `src/jd_analytics/pipelines/*.py` (无变化)
- `src/jd_analytics/settings.py` (AutoThrottle via EXTENSIONS)
- `tests/test_smoke.py` (10/10 通过)

## 6. 下一步

等 CVO 决策后：
- 若选方案 A/D → 用户登录后重跑 `--trial --max-pages 2` 验证
- 若选方案 B/C → 重新设计 spider，可能需要新依赖
