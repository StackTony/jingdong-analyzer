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

> 关羽 review 标的 P2 findings（不阻塞合入，已合入 main 后跟进）+ AC-1 Postgres 缺口。

- [ ] **P2-1 跟进**: `llm_plan_generator.py` max_tokens 已读 config（commit 122fc06 已修），但 `llm_reviewer.py` 的 `review()` 仍硬编码 `max_tokens=2000`——应同样读 config.max_tokens
- [ ] **AC-1 Postgres**: 补 `PostgresAdapter`（接生产 DB 时实现，MVP 未需要）
- [ ] **OQ-1 op_spec 漂移**: 12 op 手写维护 + 抽样测试够；P7+ 上 pydantic/introspect 自动同步 op 函数签名
- [ ] **OQ-2 晋升 N 值调优**: N=3 硬编码 MVP 跑起来观察首批晋升 plan 质量后再调
- [ ] **OQ-3 空 content 日志**: GLM-5.2 reasoning_tokens 吃光 content 为空时，加日志记录便于排查（当前靠 _parse_json ValueError 触发重试，逻辑对但缺日志）
