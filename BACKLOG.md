---
topics: [backlog]
doc_kind: note
created: 2026-08-25
---

# Feature Roadmap

> **Rules**: Only active Features (idea/spec/in-progress/review). Move to done after completion.
> Details in `docs/features/Fxxx-*.md`.

| ID | Name | Status | Owner | Link |
|----|------|--------|-------|------|
| F001 | 京东品类品牌销售数据采集 | in-progress | 奉孝 | `docs/features/F001-jd-brand-analytics.md` |
| F002 | 通用数据分析框架（双轨自进化） | in-progress | 文若/奉孝 | `docs/features/F002-universal-analytics-framework.md` |

## F002 合入后续（P7+ 候选）

> 关羽 review 标的 P2 findings（不阻塞合入，已合入 main 后跟进）+ AC-1 Postgres 缺口
> + 外部 AI review findings P1-P5（已处置）。

- [x] **P2-1 跟进**: `llm_plan_generator.py` max_tokens 已读 config（commit 122fc06 已修）；`llm_reviewer.py:40` 同模式硬编码 `max_tokens=2000` 已修（feat/f002-reviewer-max-tokens，读 `provider.config.max_tokens`，TDD 红绿 + 全量 211 passed 无回归）
- [x] **外部 AI P1**: 模板硬编码 sales/brand 列 → 列名变量化 `{{numeric_col}}` / `{{group_col}}` / `{{time_col}}` / `{{category_col}}`，`resolve_template_variables(tpl, ds)` 注入（feat/f002-review-fixes，TDD 红绿，218 passed）
- [x] **外部 AI P2**: FakePlanGenerator 趋势 Plan 用错时间列 → 新增 `_pick_time_col`，无 datetime 时退化到 aggregate（feat/f002-review-fixes，TDD 红绿）
- [x] **外部 AI P3**: 品类对比模板按 brand 聚合 → 改用 `{{category_col}}`，新增 `_pick_category_col` 偏好 category 列（feat/f002-review-fixes）
- [x] **外部 AI P4**: scan-promote 重复报告 → `scan_and_promote` 对比前后 templates 集合差，只返回新增（feat/f002-review-fixes，TDD 红绿）
- [x] **外部 AI P1-1 (B方案)**: ChartSpec.data 改 DataFrame 引用 + `to_json(max_rows=1000)` 惰性序列化，避免 33 万行 to_dict 占 +399MB 内存（feat/f002-chart-spec-arch，TDD 红绿，223 passed 无回归）
- [x] **外部 AI P1-2**: modeler.trend 内置 `pd.to_datetime` 预处理，字符串日期列自动转，无法解析抛 ValueError（feat/f002-chart-spec-arch）
- [ ] **外部 AI P5**: B 轨匹配依赖 intent 分类（未分类 intent=None 时跳过 B 轨）。符合当前规则分类器设计，**不改，记入候选**——P7+ 可考虑未分类问题的模糊匹配（embedding 相似度）
- [ ] **AC-1 Postgres**: 补 `PostgresAdapter`（接生产 DB 时实现，MVP 未需要）
- [ ] **OQ-1 op_spec 漂移**: 12 op 手写维护 + 抽样测试够；P7+ 上 pydantic/introspect 自动同步 op 函数签名
- [ ] **OQ-2 晋升 N 值调优**: N=3 硬编码 MVP 跑起来观察首批晋升 plan 质量后再调
- [ ] **OQ-3 空 content 日志**: GLM-5.2 reasoning_tokens 吃光 content 为空时，加日志记录便于排查（当前靠 _parse_json ValueError 触发重试，逻辑对但缺日志）
