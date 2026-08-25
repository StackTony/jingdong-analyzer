---
topics: [project, overview]
doc_kind: readme
created: 2026-08-25
---

# 京东品类品牌销售数据采集与分析工具

> 项目阶段：spec / MVP 设计中

## 目标

针对 11 个母婴/个护品类，每月采集京东公开页面上品牌销售/销量数据，输出 Top30 品牌榜，持续 12 个月周期。

## 品类范围

成人护理 / 婴童乳霜纸 / 棉柔巾·绵柔巾 / 婴童纸尿裤 / 婴童拉拉裤 / 婴童湿巾 / 卫生巾 / 卫生护垫 / 裤型卫生巾 / 湿厕纸 / 湿巾

## 文档结构

- `CLAUDE.md` — 项目说明（猫猫 / 铲屎官入口）
- `BACKLOG.md` — Feature 路线图
- `docs/SOP.md` — 6 步工作流
- `docs/features/` — Feature specs
- `docs/decisions/` — Architecture Decision Records
- `docs/discussions/` — 讨论沉淀
- `需求澄清.txt` — 原始客户需求

## 技术栈（拟）

- Python 3.12 + Scrapy 2.11 + scrapy-playwright + playwright-stealth
- SQLite（开发态）→ Postgres 16（生产态，按月分区表）
- pandas + pandera（清洗 + 校验）
- CSV + Parquet 双导出

详见 spec：`docs/features/F001-jd-brand-analytics.md`

## 合规边界

- 客户须提供书面授权函（采集范围 + 商业用途 + 责任承担）
- 路径白名单 + QPS 上限 + 京东用户协议合规
- 评论 PII 强制脱敏
- 详见 spec 第一章
