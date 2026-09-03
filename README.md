---
topics: [project, overview]
doc_kind: readme
created: 2026-08-25
updated: 2026-08-31
---

# 京东品类品牌销售数据采集与分析工具

> 项目阶段：F002 通用数据分析框架已合入 main（P1-P6 + LLM+ 全量）；F001 采集栈 spec / 实现中

## 项目概览

两个 feature 并行：

| ID | 名称 | 状态 | 链接 |
|----|------|------|------|
| F001 | 京东品类品牌销售数据采集 | in-progress（spec / 实现） | `docs/features/F001-jd-brand-analytics.md` |
| F002 | 通用数据分析框架（双轨自进化） | in-progress（已合入 main，待 feat-lifecycle close） | `docs/features/F002-universal-analytics-framework.md` |

本 README 聚焦 **F002 通用框架的使用说明**。F001 采集栈详见其 spec。

---

## F002 通用数据分析框架 — 使用说明

### 它能做什么

输入：Excel / CSV / SQLite（Postgres 待补）任意数据源 + 一句自然语言分析问题。
输出：清洗后数据 + 建模结果 + 可视化图 + AI 三段式文字报告。

核心特征：
- **跨数据源**：DataSource Adapter 屏蔽 Excel/CSV/DB 差异，统一产出 `Dataset`
- **流程固定 + 自进化**：A 轨模板（命中即跑 0 LLM）+ B 轨 Plan（LLM 生成复用）+ 晋升通道（B 反复成功升 A）
- **省 token**：A/B 命中走 0 LLM；兜底才调 LLM；Reviewer 可关
- **AI 辅助**：兜底时 LLM 生成 Plan；可选 Reviewer 出文字报告

### 安装

```bash
# 基础安装（Cleaner/Modeler/Visualizer/CLI/Flow Library 全可用，无 LLM）
pip install -e .

# 可选：启用真实 LLM（F002 §5.3）
pip install -e ".[ai]"

# 可选：启用 Streamlit 面板
pip install -e ".[viz]"

# 可选：启用 sklearn 聚类 op（Modeler.cluster）
pip install -e ".[ai]"   # scikit-learn 在 ai extras 里
```

### 配置 LLM Provider（可选）

若用真实 LLM（`--llm` flag），apiKey 直接配在 config 文件里（直填 `api_key` 字段）。Provider 配置文件：

```
src/clowder_analytics/config/ai_providers.yaml          # git 跟踪的模板，只留占位符 sk-xxx
src/clowder_analytics/config/ai_providers.local.yaml    # gitignored，真实 key 写这里
```

默认 provider 是 `euler-y`（csi endpoint，OpenAI 兼容协议）。配置方法：

1. 复制模板为本地配置：`cp src/clowder_analytics/config/ai_providers.yaml src/clowder_analytics/config/ai_providers.local.yaml`
2. 把 `euler-y` 下的 `api_key: sk-xxx` 占位符改成你的真实 key（`api_key_env` 可留作兜底）。

`ai_providers.local.yaml` 会被深合并覆盖主配置，且已被 `.gitignore` 忽略（`*.local.yaml`），真实 key 不入库。

配置项含义：
- `api_key: sk-xxx` — 直填 key（主路径）；真实 key 只写 local.yaml
- `api_key_env: EULER_Y_API_KEY` — 兜底：也可改用环境变量（`export EULER_Y_API_KEY=sk-xxx`），key 不入库
- `max_tokens: 4000` — 推理模型需留 reasoning_tokens 空间
- `temperature: 0.3` — Plan 生成需稳定低温
- `models: ...` — 该 provider 支持的 model 列表（`default_model` 为默认）

PowerShell 设置环境变量（兜底路径）：
```powershell
$env:EULER_Y_API_KEY = "sk-xxx"
```

bash / zsh：
```bash
export EULER_Y_API_KEY=sk-xxx
```

### CLI 使用

入口：`python -m clowder_analytics.cli <command> [args]`

#### 1. 数据源探索 — `inspect`

打印 schema、指纹、列信息、前 5 行预览。

```bash
python -m clowder_analytics.cli inspect data/sample.xlsx
python -m clowder_analytics.cli inspect data/sales.csv
```

#### 2. 端到端分析 — `run`

```bash
# 不用 LLM（走 Fake generator，验证 op 链路）
python -m clowder_analytics.cli run \
  --source data/sample.xlsx \
  --question "哪个品类销售最好？"

# 用真实 LLM（需 CSI_API_KEY）
python -m clowder_analytics.cli run \
  --source data/sample.xlsx \
  --question "Top10 品牌趋势分析" \
  --llm

# 跳过 AI Reviewer（只出数据 + 图，不要文字报告）
python -m clowder_analytics.cli run \
  --source data/sample.xlsx \
  --question "..." \
  --no-review

# 指定自定义 Flow Library 目录
python -m clowder_analytics.cli run \
  --source data/sample.xlsx \
  --question "..." \
  --lib /path/to/flow_library
```

`run` 输出：路由（A/B/fallback）+ Plan ID + 命中模板/Plan + LLM 调用数 + 耗时 + 执行步骤数 + 最终数据前 10 行 + 图表清单 +（若开启）AI Reviewer 三段式报告。

#### 3. Flow Library 管理 — `flow`

```bash
# 列出所有 A 轨模板
python -m clowder_analytics.cli flow list-templates

# 列出所有 B 轨 Plan
python -m clowder_analytics.cli flow list-plans

# 查看运行统计（A 命中率 / B 命中率 / 兜底率 / 平均 LLM 调用数）
python -m clowder_analytics.cli flow stats

# 扫描并晋升：B 轨 Plan 命中 ≥ N 次且成功率 ≥ 80% → 候选模板
python -m clowder_analytics.cli flow scan-promote
```

### Streamlit Web 面板

```bash
streamlit run src/clowder_analytics/web/app.py
```

浏览器打开 http://localhost:8501，可：
- 上传 Excel/CSV 文件
- 输入分析问题
- 选择是否启用 LLM
- 查看交互图 + AI 报告

### 冷启动模板

Flow Library 自带 3 个 A 轨模板（`src/clowder_analytics/flow_library_data/templates/`）：

| 模板 | intent | 用途 |
|------|--------|------|
| `cold_start_topn_trend.yaml` | TopN 趋势分析 | 品牌聚合 + TopN 排名 |
| `cold_start_anomaly_attribution.yaml` | 异常归因 | 异常检测 + 归因 |
| `cold_start_category_compare.yaml` | 品类对比 | 多品类横向比较 |

schema_fingerprint 为 `*`（通配），任意数据源都能命中走 A 轨 0 LLM。

### 双轨自进化机制

```
用户问题 + 数据源
      ↓
  IntentClassifier 分意图
      ↓
  Router 双轨匹配：
  ┌─ A 命中（模板）→ 0 LLM 直接执行
  ├─ B 命中（Plan）→ 0 LLM 复用执行
  └─ 都不命中 → LLM 生成新 Plan → 沉淀入库
      ↓
  PlanExecutor 串行执行 op 链
      ↓
  FlowLibrary 沉淀 RunRecord（schema 指纹 + 意图 + 命中 + 失败原因）
      ↓
  Promoter 定期扫描：
  - scan_and_promote: B 命中 ≥ 3 次且成功率 ≥ 80% → 升 A
  - check_and_demote: A 连续失败 → 降级 deprecated
```

### 测试

```bash
# 全 mock 测试（无网络，约 2 分钟）
python -m pytest tests/ --ignore=tests/test_llm_smoke.py -q

# 真实 LLM 烟测（需 CSI_API_KEY）
python -m pytest tests/test_llm_smoke.py -v
```

当前基线：**211 passed, 1 skipped**（skipped 是 sklearn 未装导致 cluster 测跳过）。

### 原子能力清单

| 类别 | op 数量 | 清单 |
|------|---------|------|
| Cleaner | 6 | `drop_empty_rows` / `fill_na` / `rename_column` / `drop_column` / `filter_rows` / `cast_type` |
| Modeler | 6 | `group_by_agg` / `pivot_table` / `merge` / `sort` / `compute` / `descriptive_stats` |
| Visualizer | 4 类 | `bar` / `line` / `pie` / `scatter` |

op args schema 集中维护在 `src/clowder_analytics/atomic/op_spec.py`，注入 LLM prompt 防止模型瞎编字段名。

### 目录结构

```
src/clowder_analytics/
├── adapters/           # DataSource Adapter（Excel/CSV/SQLite）
├── ai/                 # LLM Provider + Plan Generator + Reviewer
├── atomic/             # Cleaner/Modeler/Visualizer 原子能力 + op_spec
├── cli/                # CLI 入口（python -m clowder_analytics.cli）
├── config/             # ai_providers.yaml 等
├── flow_library/       # Plan/RunRecord 持久化 + Promoter + Dashboard
├── flow_library_data/  # templates/ plans/ runs/（实际数据落盘）
├── orchestrator/       # Router + IntentClassifier + PlanExecutor + run()
└── web/                # Streamlit 面板
```

---

## F001 采集栈（spec / 实现中）

详见 `docs/features/F001-jd-brand-analytics.md`。本 README 不展开。

---

## 文档结构

- `CLAUDE.md` — 项目说明（猫猫 / 铲屎官入口）
- `BACKLOG.md` — Feature 路线图 + P7+ 候选
- `docs/SOP.md` — 6 步工作流
- `docs/features/` — Feature specs
- `docs/decisions/` — Architecture Decision Records
- `docs/discussions/` — 讨论沉淀
- `需求澄清.txt` — 原始客户需求

## 技术栈

- Python ≥ 3.10
- pandas + pyarrow + sqlalchemy + structlog
- plotly（Visualizer）/ streamlit（Web 面板）/ scikit-learn（聚类，可选）
- openai SDK（LLM 真实接入，OpenAI 兼容协议）

## 合规边界（F001 采集栈）

- 客户须提供书面授权函（采集范围 + 商业用途 + 责任承担）
- 路径白名单 + QPS 上限 + 京东用户协议合规
- 评论 PII 强制脱敏
- 详见 F001 spec 第一章
