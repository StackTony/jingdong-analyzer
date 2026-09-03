---
feature_ids: [F002]
related_features: [F001]
topics: [data-analysis, ai-assisted, self-evolving, framework, token-saving]
doc_kind: spec
created: 2026-08-31
owner: 荀彧/文若 (@cat-rp3g6qqr)
status: in-progress
reviewers:
  - 郭嘉/奉孝 (@ragdoll-pa82) — 架构 review
  - 关羽/云长 (@cat-ko094z1n) — 代码质量 review (已放行 LGTM 2026-08-31)
---

# F002: 通用数据分析框架（方案 C — 双轨自进化）

> Status: in-progress | Owner: 荀彧/文若 (@cat-rp3g6qqr)
> 架构方案: C（双轨 = A 模板库 + B Plan 库 + 晋升通道）
> 上游决策: 铲屎官 2026-08-31 拍板（"通用框架 + 自进化 + 省 token"）

## Timeline

| 日期 | 事件 |
|------|------|
| 2026-08-31 | spec 定稿（方案 C 双轨自进化，铲屎官拍板） |
| 2026-08-31 | P1-P6 + 真实 LLM 接入实现完成（11 commits, 63 files, +6852 lines） |
| 2026-08-31 | 关羽跨家族 review 放行（LGTM，覆盖 SHA 1c9d835） |
| 2026-08-31 | P2 findings TDD 修复（commit 122fc06，关羽延续放行） |
| 2026-08-31 | 本地 merge feat → main（merge commit 57e454f，铲屎官授权绕过 merge-gate） |
| 2026-08-31 | push origin/main（57e454f） |
| 2026-08-31 | P2-1 同模式漏网修复：`llm_reviewer.py:40` 硬编码 max_tokens=2000 → 读 `provider.config.max_tokens`（feat/f002-reviewer-max-tokens，TDD 红绿，211 passed 无回归） |
| 2026-08-31 | 外部 AI review P1-P4 修复：模板列名变量化（P1+P3）+ FakePlanGenerator 趋势用 datetime 列（P2）+ scan-promote 幂等报告（P4）。P5 记入 BACKLOG 候选（feat/f002-review-fixes，TDD 红绿，218 passed 无回归） |
| 2026-09-01 | 外部 AI review P1-1 B方案 + P1-2 修复：`ChartSpec.data` 改 DataFrame 引用 + `to_json(max_rows=1000)` 惰性序列化（避免 33 万行 to_dict 占 +399MB 内存）；`modeler.trend` 内置 `pd.to_datetime` 预处理（feat/f002-chart-spec-arch，TDD 红绿，223 passed 无回归）。架构改动 @文若 spec review 待签字 |
| 2026-09-02 | 大数据量优化 G1+G2+G3：3 adapter 支持 `max_rows` 采样加载（CSV nrows / Excel nrows+openpyxl 流式数行 / SQLite LIMIT N）；`render(max_rows=N)` 采样喂 plotly；web app `_render_chart` 内置 `WEB_RENDER_MAX_ROWS=50` 闭环 B 方案 `to_json`（feat/f002-big-data-opt，TDD 红绿，231 passed 无回归）。适配铲屎官数据量级 11 品类 × 万 url |
| 2026-09-02 | 通用 LLM 多 provider 多 model 对接 G13：`ai_providers.yaml` 新格式 `providers.<name>.models.<model_id>` map + `default_model` 字段；`load_provider(name, model)` 运行时选 provider 下任意 model；向后兼容老格式顶层 `model`；新增 glm / euler-y 配置示例（feat/f002-llm-multi-provider，TDD 红绿，237 passed 无回归） |
| 2026-09-02 | 模型展示 + 切换 + api_key 直填 G14：`api_key` 直填字段（AI SDK 风格，优先于 `api_key_env`，私有网关免环境变量）；`list_providers()` 枚举 + `get_default_provider_name()` 兜底；web sidebar Provider/Model selectbox + 当前模型展示；CLI `--llm-model` 参数。euler-y 精简为 csi endpoint 单 provider 5 model（GLM-5.3-Flash / GLM-5.3 / Qwen3.8-Flash / DeepSeek-V4-Pro / MiniMax-M3，key 限 pool_0010）。三 model 连通性实测 OK（feat/f002-model-switch，TDD 红绿，248 passed 无回归） |
| 2026-09-03 | **P0 安全事故止损 + merge main**：关羽 review 发现 G14 初版把真实 csi key 明文 commit（0982091）并 push 到公开仓库。止损三件套：① 代码层撤出（生产 yaml 改 `api_key_env: EULER_Y_API_KEY`，测试 fixture 换假 key + localhost，docstring 修正）② force-push 重写分支历史（squash 为 c0322b6，tree 与关羽复核放行的 2ef4555 一致，含 key 的 0982091/0b3852c 从远端抹除）③ 铲屎官 revoke key。教训沉淀：公开仓库 yaml 永远走 env，key 哪怕"泄露面可控"也不入库 |

## Why

铲屎官要做的不只是"分析京东品类数据"，而是一个**能反复用、跨数据源、AI 辅助、且能在使用中自进化、节省 token 消耗**的通用分析框架。

直接痛点：
- 数据分析流程高度固定（同类问题反复出现），但每次让 LLM 重新推理 = token 浪费
- 现有代码（F001 京东爬虫栈）强绑京东 SPU/SKU/评价数差值口径，不可复用为"通用"
- 需要"流程固定但能自进化"——既要命中已知流程走捷径（省 token），又要能处理新场景并沉淀

方案 C 用"双轨 + 晋升"机制同时满足这三个诉求：A 轨模板（命中即跑 0 LLM）+ B 轨 Plan（LLM 生成复用）+ 晋升通道（B 反复成功升 A）。

## What

一个通用数据分析框架，输入是 Excel/CSV/SQLite/Postgres 任意数据源 + 自然语言分析问题，输出是清洗后数据 + 建模结果 + 可视化图 + AI 文字报告。框架内置 7 个模块化组件、3 种沉淀形态（A 模板/B Plan/运行日志）、晋升机制（B→A）、双轨调度器。

核心特征：
- **跨数据源**：DataSource Adapter 抽象层屏蔽 Excel/CSV/DB 差异
- **流程固定**：原子能力集（Cleaner/Modeler/Visualizer）声明式调用，参数化
- **自进化**：B 轨 Plan 自动生成入库；A 轨模板可由 Plan 晋升
- **省 token**：A/B 命中走 0 LLM；兜底才调 LLM；Reviewer 可关
- **AI 辅助**：兜底时 LLM 生成 Plan；可选 Reviewer 出文字报告

## Acceptance Criteria

- [~] AC-1: DataSource Adapter 至少支持 4 种源（Excel xlsx / CSV / SQLite / Postgres connection），统一产出 `Dataset` 对象（DataFrame + schema 指纹 + 元数据）
  - ✅ Excel / CSV / SQLite 三种已实现（`src/clowder_analytics/adapters/{excel,csv,sqlite}.py`）
  - ⬜ Postgres 未实现（MVP 阶段未需要，后续接入生产 DB 时补）
- [x] AC-2: 原子能力集至少覆盖：Cleaner 6 个（去重/缺值/类型转换/异常值/标准化/字段映射）、Modeler 6 个（聚合/TopN/趋势/相关性/聚类/异常归因）、Visualizer 4 类（柱/折线/散点/热力）
  - ✅ Cleaner 6 op + Modeler 6 op + Visualizer 4 类（cluster 需 sklearn，未装时跳过）
- [x] AC-3: A 轨模板 YAML 声明式可读，支持两种产生方式（LLM 直生成 / B 轨 Plan 晋升），均经人工审核入稳定库；包含 schema 指纹匹配条件 + 原子能力调用序列 + 参数
- [x] AC-4: B 轨 Plan JSON 声明式，含执行序列 + 失败处理策略（abort_on_first_error / continue_on_error）+ 用户反馈字段
- [x] AC-5: 晋升机制：Plan 在同 schema 指纹 + 同意图下命中执行 ≥ N（默认 3）次且成功率 ≥ 80% → 自动入候选；人工审核后入稳定库
  - ✅ `promoter.py::check_promote` (N=3 + 80%) + `promote` 幂等 + `scan_and_promote` (P2-2 修复后覆盖所有 route)
- [x] AC-6: 双轨调度：Router 按 (schema 指纹, 意图) 匹配 A → B → 兜底 LLM 生成，命中即跳过下游 LLM 调用
  - ✅ `router.py` A→B→fallback 三层匹配
- [x] AC-7: AI Reviewer 可关闭；开启时输出"异常解释 + 趋势点睛 + 建议下一步"三段式文字报告
  - ✅ `llm_reviewer.py` + 真实 LLM 烟测三段式报告验证
- [x] AC-8: CLI 入口 `jd-analyze run --source <path> --question <text>` 跑通端到端
  - ✅ `cli/__main__.py` 含 `--llm` flag
- [x] AC-9: Streamlit 面板支持上传 Excel + 选分析模式 + 看交互图 + AI 报告
  - ✅ `web/app.py`
- [x] AC-10: Flow Library 自带 ≥ 3 个 A 轨模板冷启动样本（TopN 趋势 / 异常归因 / 品类对比）
  - ✅ `flow_library_data/templates/cold_start_*.yaml` 三个模板
- [x] AC-11: 运行日志记录每次执行的 (schema 指纹, 意图, 命中模板/Plan, 失败原因, 用户采纳, 修正建议)，可查询
  - ✅ `flow_library/store.py::save_run` 写 `runs/runs.jsonl`
- [x] AC-12: 长期收敛指标可观测：A 命中率 / B 命中率 / 兜底率 / 平均 LLM 调用数 → 仪表盘可见
  - ✅ `flow_library/dashboard.py`

## Dependencies

- **复用**：F001 的 pandas + pyarrow + sqlalchemy + structlog 技术栈
- **新增依赖**（拟）：
  - `plotly>=5.0` — 可视化（静态 + 交互）
  - `streamlit>=1.30` — Web 面板
  - `scikit-learn>=1.3` — Modeler 聚类/异常检测（可选）
  - `anthropic` 或 `openai` SDK — AI Reviewer + 兜底 Plan 生成
  - `jinja2` — A 轨模板参数化（拟）
- **不依赖**：F001 的 Scrapy / DrissionPage / PaddleOCR（爬虫栈不复用）

## Risk

详见 §10 风险登记表。

---

## 目录

1. [设计原则](#1-设计原则)
2. [模块视图](#2-模块视图)
3. [DataSource Adapter](#3-datasource-adapter)
4. [Cleaner / Modeler / Visualizer 原子能力集](#4-cleaner--modeler--visualizer-原子能力集)
5. [AI Reviewer + Plan 生成器](#5-ai-reviewer--plan-生成器)
6. [Orchestrator 双轨调度](#6-orchestrator-双轨调度)
7. [Flow Library 与自进化机制](#7-flow-library-与自进化机制)
8. [CLI + Streamlit 入口](#8-cli--streamlit-入口)
9. [目录结构](#9-目录结构)
10. [风险登记表](#10-风险登记表)
11. [Phase 路线图](#11-phase-路线图)
12. [待决策点](#12-待决策点)

---

## 1. 设计原则

| 原则 | 含义 |
|------|------|
| **流程固定优先** | 同类问题反复出现 → 沉淀成模板，不每次重新推理 |
| **自进化** | 新场景 LLM 生成 Plan → 反复成功 → 晋升为模板 |
| **省 token** | A/B 命中走 0 LLM；Reviewer 可关；兜底才调 LLM |
| **声明式** | A 模板 YAML / B Plan JSON，可 diff/版本化/回滚 |
| **原子能力** | Cleaner/Modeler/Visualizer 是小而独立的函数，单一职责，可独立测试 |
| **可观测** | 运行日志 + 命中率仪表盘，自进化效果可量化 |
| **跨数据源** | DataSource Adapter 抽象层屏蔽源差异 |

---

## 2. 模块视图

```
                    ┌─────────────────────────────────────────┐
                    │           用户入口 (CLI / Streamlit)      │
                    │  问 + 数据源描述（path/conn_str + schema 提示）│
                    └────────────────────┬────────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │   Orchestrator      │  ← 双轨调度 + 沉淀入口
                              │   (Router/Executor) │
                              └──┬───┬───┬───┬───┬──┘
       ┌─────────────────────────┘   │   │   │   │
       │             ┌───────────────┘   │   │   └──────────────┐
       ▼             ▼                   ▼   ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐
│ DataSource │ │  Cleaner   │ │  Modeler   │ │Visualizer│ │   AI     │
│  Adapter   │ │ (atomic)   │ │ (atomic)   │ │(atomic)  │ │ Reviewer │
└────────────┘ └────────────┘ └────────────┘ └──────────┘ └──────────┘
       │             │               │           │           │
       └─────────────┴───────────────┴───────────┴───────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Flow Library      │  ← A 轨模板 + B 轨 Plan 沉淀
                    │  (templates/ plans/ │     + 执行日志 + 晋升记录
                    │   runs/ memory)    │
                    └────────────────────┘
```

### 模块职责一览

| 模块 | 职责 | 对外接口 | 依赖 |
|------|------|---------|------|
| DataSource Adapter | Excel/CSV/DB → 统一 `Dataset` | `load(source_desc) → Dataset` | pandas, sqlalchemy, pyarrow |
| Cleaner | 原子清洗函数集（声明式调用） | `apply(op, args, df) → df + report` | pandas |
| Modeler | 原子建模/分析函数集 | `apply(op, args, df) → result + chart_spec` | pandas, sklearn 可选 |
| Visualizer | chart_spec → 图（静态/交互） | `render(chart_spec, mode) → fig` | plotly |
| AI Reviewer | 数据+图 → 文字结论 | `review(summary, charts, log) → text` | anthropic/openai SDK |
| Orchestrator | 双轨调度 + 沉淀入口 | `run(question, source) → result` | 全部 |
| Flow Library | 模板/Plan/日志存储与检索 | `match(fp, intent) → plan; save(run); promote()` | 文件 + SQLite |

---

## 3. DataSource Adapter

### 3.1 Dataset 对象（核心抽象）

```python
@dataclass
class Dataset:
    df: pd.DataFrame              # 数据本体
    schema_fingerprint: str       # 列名+类型 hash（用于模板/Plan 匹配）
    metadata: dict                # 源信息（path/conn_str/sheet/row_count/...）
    source_type: str              # excel / csv / sqlite / postgres
    columns: list[ColumnSpec]     # 列声明（name, dtype, semantic_hint）

@dataclass
class ColumnSpec:
    name: str
    dtype: str                     # int64/float64/object/datetime64
    semantic_hint: str | None      # "category" / "brand" / "sales" / "date"（可选，LLM 推断或用户声明）
```

### 3.2 Adapter 接口

```python
class DataSourceAdapter:
    def load(self, source_desc: SourceDesc) -> Dataset: ...
    def supported_types(self) -> list[str]: ...
```

`SourceDesc` 是用户声明的数据源描述（path 或 conn_str + 可选 sheet/table/查询条件）。

### 3.3 内置 Adapter（MVP）

| Adapter | 输入 | 备注 |
|---------|------|------|
| ExcelAdapter | `.xlsx` / `.xls` | 多 sheet 支持 |
| CsvAdapter | `.csv` / `.tsv` | 自动编码检测 |
| SqliteAdapter | `sqlite:///<path>` | 接 F001 现有 sqlite 资产 |
| PostgresAdapter | `postgresql://...` | 生产态 |

### 3.4 schema 指纹算法（拟，待奉孝对撞）

**倾向**：列名（小写归一化）+ dtype 的稳定 hash。不含样本值（会变）。

```python
def compute_fingerprint(df: pd.DataFrame) -> str:
    cols = sorted((c.lower(), str(df[c].dtype)) for c in df.columns)
    return hashlib.sha256(json.dumps(cols).encode()).hexdigest()[:16]
```

---

## 4. Cleaner / Modeler / Visualizer 原子能力集

### 4.1 设计约束

- 每个原子能力是**单一职责的纯函数**：`f(df, **args) -> (df_or_result, op_report)`
- 输入输出可序列化（Plan 调用参数是 JSON）
- 每个能力自带 `spec()` 返回 `(name, args_schema, description)`，供 LLM 生成 Plan 时检索
- 失败抛 `OpError`，不吞异常

### 4.2 Cleaner 原子集（MVP 6 个）

| op_name | args | 行为 |
|---------|------|------|
| `remove_duplicates` | `keys: list[str]`, `keep: "first"\|"last"\|"max_review"` | 按 keys 去重（keep=max_review 需指定 review_col） |
| `fill_missing` | `columns: list[str]`, `strategy: "mean"\|"median"\|"zero"\|"ffill"\|"drop"` | 缺值填充 |
| `convert_types` | `column_types: dict[str, str]` | 类型转换（"int"/"float"/"datetime"/"category"） |
| `remove_outliers` | `column: str`, `method: "iqr"\|"zscore"`, `threshold: float` | 异常值剔除 |
| `normalize_text` | `columns: list[str]`, `ops: ["trim","lower","strip_punct"]` | 文本标准化（品牌名归一化等） |
| `map_fields` | `mapping: dict[str, str]` | 字段重命名/映射（语义层归一） |

### 4.3 Modeler 原子集（MVP 6 个）

| op_name | args | 输出 |
|---------|------|------|
| `aggregate` | `group_by: list[str]`, `agg: dict[str, "sum"\|"mean"\|"count"]` | 聚合后 df + chart_spec |
| `topn` | `group_by: list[str]`, `value_col: str`, `n: int`, `rank_by: "value"\|"volume"` | TopN df + chart_spec |
| `trend` | `time_col: str`, `value_col: str`, `freq: "M"\|"W"\|"D"` | 时序 df + chart_spec |
| `correlation` | `columns: list[str]`, `method: "pearson"\|"spearman"` | 相关性矩阵 + 热力图 chart_spec |
| `cluster` | `columns: list[str]`, `k: int`, `method: "kmeans"` | 聚类标签 df + chart_spec |
| `anomaly_attribution` | `value_col: str`, `group_by: list[str]`, `baseline: str` | 异常归因表 + chart_spec |

### 4.4 Visualizer 原子集

`render(chart_spec: ChartSpec, mode: "static"\|"interactive") -> Figure`

ChartSpec 是 Modeler 输出的声明式图表描述，`type` 字段枚举对应 AC-2 的 4 类：
- `bar` — 柱状图（TopN / 聚合结果）
- `line` — 折线图（趋势）
- `scatter` — 散点图（相关性 / 分布）
- `heatmap` — 热力图（相关性矩阵 / 品类对比）

静态模式输出 PNG/HTML，交互模式输出 Streamlit component（plotly 两种形态同源）。

---

## 5. AI Reviewer + Plan 生成器

### 5.1 Plan 生成器（兜底时调用）

**触发**：Router 在 A/B 都未命中时调用。

**输入**：用户问题 + Dataset（schema 摘要 + 前 N 行样本 + 统计信息）+ 可用原子能力清单（每个能力的 spec）

**输出**：B 轨 Plan（JSON）

```json
{
  "plan_id": "<auto-gen-uuid>",
  "intent": "TopN 趋势分析",
  "schema_fingerprint": "<matches input>",
  "steps": [
    {"op": "clean.remove_duplicates", "args": {"keys": ["spu_id"], "keep": "first"}},
    {"op": "clean.normalize_text", "args": {"columns": ["brand_name"], "ops": ["trim","lower"]}},
    {"op": "model.topn", "args": {"group_by": ["brand_name"], "value_col": "sales", "n": 30, "rank_by": "value"}}
  ],
  "reviewer_enabled": true,
  "fallback_strategy": "abort_on_first_error"
}
```

**LLM prompt 结构**（系统提示词核心要素，完整模板见实施计划阶段）：
- 角色：数据分析 Plan 生成器
- 工具清单：所有原子能力的 `spec()` 拼接
- 约束：只能调用清单内的能力；args 必须符合 args_schema
- 输出：严格 JSON（带 schema 校验，失败重试一次）

### 5.2 AI Reviewer（可选调用）

**触发**：Plan 执行完后，如果 `reviewer_enabled=true`。

**输入**：数据摘要（聚合后统计 + 异常列表）+ 图表 PNG base64 + 执行日志

**输出**：三段式文字报告
- 异常解释：检测到的异常及其可能原因
- 趋势点睛：关键趋势 / 排名变迁 / 结构性变化
- 建议下一步：推荐的下一步分析方向

**可关闭**：CLI 加 `--no-review` / Streamlit 面板 checkbox。

### 5.3 LLM 模型配置（待奉孝对撞）

倾向：可配置 + 默认 GLM-4.6（家里自己和奉孝都是 GLM，省跨家成本）。`config/ai_providers.yaml` 声明多 provider，运行时按 env 切换。

---

## 6. Orchestrator 双轨调度

### 6.1 Router 匹配逻辑

```python
def route(question, dataset) -> Route:
    fp = dataset.schema_fingerprint
    intent = classify_intent(question)  # 关键词/规则分类

    # 1. A 轨匹配（精确指纹 + 意图）
    template = flow_library.match_template(fp, intent)
    if template and template.confidence >= THRESHOLD_A:
        return Route("A", template=template)

    # 2. B 轨匹配（指纹相似度 + 意图）
    plan = flow_library.match_plan(fp, intent)
    if plan and plan.confidence >= THRESHOLD_B:
        return Route("B", plan=plan)

    # 3. 兜底：LLM 生成新 Plan
    return Route("fallback", generate=True)
```

### 6.2 Executor 执行逻辑

```python
def execute(route: Route, dataset: Dataset) -> RunResult:
    plan = route.template.to_plan() if route.kind == "A" else route.plan
    if route.generate:
        plan = ai_plan_generator.generate(dataset, route.intent)

    df = dataset.df
    run_log = []
    for step in plan.steps:
        try:
            df, op_report = atomic_ops[step.op].apply(df, **step.args)
            run_log.append({"step": step.op, "ok": True, "report": op_report})
        except OpError as e:
            run_log.append({"step": step.op, "ok": False, "err": str(e)})
            if plan.fallback_strategy == "abort_on_first_error":
                break

    charts = [visualizer.render(spec) for spec in collect_chart_specs(run_log)]
    review = ai_reviewer.review(dataset, charts, run_log) if plan.reviewer_enabled else None

    # 沉淀
    flow_library.save_run(RunRecord(...))

    return RunResult(df=df, charts=charts, review=review, log=run_log, route=route.kind)
```

### 6.3 意图分类器

倾向：**规则 + 关键词**起步（"TopN" / "趋势" / "异常" / "对比" / "相关"），冷启动不要 embedding。后期可升级为向量检索。

---

## 7. Flow Library 与自进化机制

### 7.1 三种沉淀形态

| 形态 | 载体 | 产生方式 | 命中后 LLM |
|------|------|---------|-----------|
| A 轨模板 | `flow_library/templates/*.yaml` | LLM 生成 Plan → 反复成功 → 自动晋升 + 人工审核 | 0 次 |
| B 轨 Plan | `flow_library/plans/*.json` | LLM 兜底生成 + 入库 | 0 次（复用） |
| 运行日志 | `flow_library/runs/*.jsonl` | 每次执行自动记录 | — |

### 7.2 A 轨模板 YAML 结构（拟，待奉孝对撞）

```yaml
template_id: topn_brand_sales_trend
version: 1
intent: TopN 趋势分析
schema_fingerprint_match:
  mode: exact  # exact | fuzzy
  fingerprint: "<sha256-hash>"
  column_hints:  # 兜底（指纹不完全匹配时按列名兜底）
    - brand_name: ["brand","品牌"]
    - sales: ["sales","销量","销售额"]
    - date: ["date","month","月份"]
steps:
  - op: clean.remove_duplicates
    args: {keys: [spu_id], keep: first}
  - op: clean.normalize_text
    args: {columns: [brand_name], ops: [trim, lower]}
  - op: model.topn
    args: {group_by: [brand_name], value_col: sales, n: 30, rank_by: value}
reviewer_enabled: true
fallback_strategy: abort_on_first_error
created_at: 2026-08-31
promoted_from_plan_id: <plan-uuid>  # 从哪个 B 轨 Plan 晋升而来
stability: candidate  # candidate | stable | deprecated
```

### 7.3 A 轨模板的产生与晋升

A 轨模板有**两种产生路径**，均统一进入 candidate → stable 审核流程：

**路径 1：B 轨 Plan 晋升（主路径）**
- 触发条件（拟，待奉孝对撞）：
  - 某 Plan 在 `(schema_fingerprint, intent)` 下被命中执行 ≥ **N=3** 次
  - 且成功率 ≥ **80%**
  - 且无人工修正（用户未拒绝 + 未手动改 args）
- 满足条件 → 自动晋升为 A 轨模板，`stability=candidate`

**路径 2：LLM 直接生成（冷启动 / 新意图）**
- 触发：用户/开发者通过 CLI `jd-analyze flow new-template --question "..." --source ...` 让 LLM 直接产出 A 轨模板（而非走 Plan 沉淀）
- 适用：冷启动期（AC-10 内置样本）、新意图但无对应 Plan 反复命中
- 产生即 `stability=candidate`

**统一审核流程**：
1. 两种路径产生的模板均进入"待审核"队列（candidate）
2. 人工审核（CLI `jd-analyze flow review-candidates`）→ 入 `stable` 或回退或删除
3. `stable` 模板参与精确匹配；`candidate` 仅在 `stable` 无命中时兜底

### 7.4 降级 / 弃用

- A 轨模板连续 K=5 次失败 → 自动降级为 `deprecated`，不再参与匹配
- 用户可手动恢复或删除

### 7.5 运行日志结构

```json
{
  "run_id": "<uuid>",
  "timestamp": "2026-08-31T...",
  "schema_fingerprint": "<hash>",
  "intent": "TopN 趋势分析",
  "route": "A|B|fallback",
  "matched_template_id": "..." | null,
  "matched_plan_id": "..." | null,
  "steps": [...],
  "success": true,
  "user_adopted": null,  # 三态：null=未反馈 / true=采纳 / false=拒绝
  "user_correction": null,
  "llm_calls": 0 | 1 | 2,
  "duration_ms": 1234
}
```

### 7.6 仪表盘

CLI `jd-analyze flow stats` 输出：
- A 命中率 / B 命中率 / 兜底率（最近 7/30/全部）
- 平均 LLM 调用数
- 候选模板队列长度
- Top 5 高频 intent

---

## 8. CLI + Streamlit 入口

### 8.1 CLI 入口（拟）

```bash
# 端到端跑分析
jd-analyze run --source data.xlsx --question "找出销售额 Top30 品牌趋势"
jd-analyze run --source sqlite:///jd.db --question "..." --no-review

# Flow Library 管理
jd-analyze flow list-templates
jd-analyze flow list-plans
jd-analyze flow review-candidates
jd-analyze flow stats

# 数据源探索
jd-analyze source inspect data.xlsx
```

### 8.2 Streamlit 面板（拟）

单页应用：
- 左侧：上传 Excel / 选 DB 连接 → 显示 schema + 指纹
- 中间：选分析意图（下拉 + 自然语言输入）→ 显示命中的 A/B/兜底路径
- 右侧：交互图 + AI 报告 + "采纳/拒绝"按钮（反馈写回运行日志）

---

## 9. 目录结构

```
src/jd_analytics/
├── adapters/                  # DataSource Adapter
│   ├── __init__.py
│   ├── base.py                # Dataset, ColumnSpec, DataSourceAdapter
│   ├── excel.py
│   ├── csv.py
│   ├── sqlite.py
│   └── postgres.py
├── atomic/                    # 原子能力集
│   ├── __init__.py
│   ├── cleaner.py             # 6 个清洗 op
│   ├── modeler.py             # 6 个建模 op
│   ├── visualizer.py          # plotly 渲染
│   └── registry.py            # op spec 注册表（供 LLM 检索）
├── ai/
│   ├── __init__.py
│   ├── plan_generator.py      # 兜底 Plan 生成
│   ├── reviewer.py            # 三段式文字报告
│   └── providers.yaml          # LLM provider 配置
├── orchestrator/
│   ├── __init__.py
│   ├── router.py              # 双轨匹配
│   ├── executor.py            # Plan 执行
│   └── intent_classifier.py   # 规则起步
├── flow_library/
│   ├── __init__.py
│   ├── store.py               # 模板/Plan/日志 CRUD
│   ├── matcher.py             # 指纹 + 意图匹配
│   └── promoter.py            # B→A 晋升逻辑
├── cli/
│   ├── __init__.py
│   ├── run.py                 # jd-analyze run
│   ├── flow.py                # jd-analyze flow *
│   └── source.py              # jd-analyze source *
├── web/
│   ├── __init__.py
│   └── app.py                 # Streamlit 面板
├── config/
│   ├── atomic_ops.yaml        # 原子能力清单（给 LLM 的工具描述）
│   └── ai_providers.yaml
└── flow_library_data/         # 持久化（gitignored 或单独 repo）
    ├── templates/
    ├── plans/
    └── runs/
```

**注意**：与 F001 现有 `src/jd_analytics/` 同名包。拟处理方式见 §12 待决策点 D5。

---

## 10. 风险登记表

| ID | 风险 | 影响 | 缓解 |
|----|------|------|------|
| R1 | A 轨模板命中率长期低 → 自进化效果不可见 → 沦为方案 B | 失去"省 token"核心价值 | 冷启动期内置 ≥3 个稳定模板（AC-10）+ 长期追踪命中率仪表盘（AC-12） |
| R2 | LLM 生成的 Plan 质量参差 → B 轨命中率低 → 兜底率高 → token 消耗不降 | 用户体验差 + 自进化失败 | Plan 生成时严格 schema 校验 + 失败重试 1 次 + 沉淀前人工审核门槛 |
| R3 | schema 指纹算法过严（exact 匹配）→ 列名小变化即脱靶 | 命中率低 | 模板支持 column_hints 兜底匹配（§7.2）+ 后期加 fuzzy 模式 |
| R4 | 晋升 N=3 太低 → 误晋升偶然成功的烂 Plan | 模板库被污染 | 加"候选 → 稳定"人工审核门槛（§7.3）+ 降级机制（§7.4） |
| R5 | 原子能力集抽象不当 → 难以表达复杂分析（如多步依赖、条件分支） | 表达力不足 | MVP 不支持分支/循环，复杂场景走兜底；后期按需扩展 Plan 语法 |
| R6 | LLM 调用不稳定（限流/超时） → 兜底失败 | 用户体验差 | Plan 生成 + Reviewer 都有重试 + 超时；失败时不阻塞已有结果输出 |
| R7 | 与 F001 代码包名冲突（都叫 jd_analytics） | import 歧义 | 见 §12 D5 |
| R8 | 数据源 schema 指纹相同但语义不同（同名不同义列） → 错误命中 | 跑出错误结果 | column_hints + 用户可手动指定 template_id（覆盖路由） |
| R9 | 用户体验"采纳/拒绝"反馈率低 → 自进化数据稀缺 | 自进化停滞 | Streamlit 默认弹反馈；CLI 末尾问一句；不反馈按 null 记 |
| R10 | 通用框架与京东 F001 代码长期耦合 → "通用"被侵蚀 | 失去复用价值 | F002 物理独立包（见 §12 D5）+ 不 import F001 业务模块；F001 后期作为 F002 的 use case，通过通用 DataSource Adapter 接 Excel/SQLite 输入（不调 F001 内部代码） |

---

## 11. Phase 路线图

| Phase | 内容 | AC 覆盖 | 备注 | 状态 |
|-------|------|---------|------|------|
| P1 | DataSource Adapter + 原子能力集骨架 + Dataset 抽象 | AC-1, AC-2 | 不含 AI / 双轨，先跑通"读 Excel → 清洗 → 出图"直线 | ✅ |
| P2 | Orchestrator + Flow Library 存储 + 单轨（B 轨 Plan） | AC-4, AC-6, AC-11 | 先 B 后 A，降低冷启动难度 | ✅ |
| P3 | AI Plan 生成器 + Reviewer | AC-3, AC-5, AC-7 | LLM 兜底 + 文字报告 | ✅ |
| P4 | A 轨模板 + 晋升机制 + 仪表盘 | AC-5, AC-10, AC-12 | 自进化闭环 | ✅ |
| P5 | CLI 完整入口 + Streamlit 面板 | AC-8, AC-9 | 交付形态 | ✅ |
| P6 | 内置 ≥3 个稳定模板冷启动样本 + 长期命中率观测 | AC-10, AC-12 | 验证自进化效果 | ✅ |
| LLM+ | 真实 GLM-5.2 接入 + op_spec args schema 注入 + P2 findings TDD 修复 | AC-3, AC-5, AC-7 | 替换 P3 Fake 实现，真实 LLM 端到端验证 | ✅ |

**MVP 里程碑**：P1+P2+P3 跑通"读 Excel → 兜底生成 Plan → 执行 → 出图 + AI 报告 → 沉淀"端到端。P4 是自进化真正生效的里程碑。

---

## 12. 待决策点（需和奉孝对撞）

### D1: A 轨模板载体格式
- **倾向**：YAML 声明式 + 嵌入式参数（不嵌入代码）
- **备选**：Python DSL（表达力强但不可被 LLM 直接生成）
- **理由**：YAML 可读可 diff，LLM 可直接生成，符合"省 token"目标

### D2: B 轨 Plan 检索机制
- **倾向**：规则指纹（schema hash + 意图关键词）起步
- **备选**：向量检索（依赖 embedding 模型，冷启动成本高）
- **理由**：冷启动无 embed 依赖，命中率足够后再升级

### D3: 晋升条件 N 值
- **倾向**：N=3 + 人工审核门槛（candidate → stable）
- **备选**：N=5 全自动 / N=3 全自动
- **理由**：过低误晋升，过高卡在 B 轨；加审核门槛平衡

### D4: DataSource schema 指纹算法
- **倾向**：列名小写归一 + dtype hash
- **备选**：列名+dtype+样本值统计 / 纯列名
- **理由**：稳定（样本值会变），区分度够

### D5: 与 F001 代码包名冲突处理
- **倾向**：F002 独立包名 `jd_analytics_framework`（或 `clowder_analytics`），不与 F001 共享 src/jd_analytics
- **备选**：F002 放 F001 包内子模块 `jd_analytics.framework`
- **理由**：F001 强绑京东语义，F002 要通用，物理隔离避免侵蚀；后期 F001 的京东分析可作为 F002 的 use case

### D6: AI Reviewer 默认 LLM
- **倾向**：可配置 + 默认 GLM-4.6（家里主 model，省跨家成本）
- **备选**：默认 Claude / 默认 OpenAI
- **理由**：铲屎官家里自己和奉孝都是 GLM

### D7: 是否在 MVP 支持 Plan 分支/循环
- **倾向**：MVP 不支持（Plan 是线性 step 列表）
- **备选**：MVP 支持简单 if-else 分支
- **理由**：MVP 复杂度控制；复杂场景走兜底 LLM

### D8: 持久化目录是否单独 repo
- **倾向**：`flow_library_data/` gitignored，单独 repo 或子目录管理
- **备选**：跟随主 repo 入库
- **理由**：模板/Plan 是"知识资产"不是代码，长期会膨胀，独立管理更轻

---

## 后续

本 spec 经奉孝架构 review + 铲屎官确认后，调用 writing-plans skill 出实施计划。

