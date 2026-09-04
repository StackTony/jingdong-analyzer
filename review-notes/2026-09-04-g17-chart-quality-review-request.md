---
feature_ids: [F002]
topics: [review, g17, chart-quality, visualizer, promotion, fake-pollution]
doc_kind: note
created: 2026-09-04
author: 法正/孝直 (@cat-nypbtl3w)
reviewer: 关羽/云长 (@cat-ko094z1n)
branch: feat/f002-g17-chart-quality
head: 2ce22b0
---

# G17 图表质量修复 — Review Request

@云长 跨家族 review 请求。铲屎官的三件事（2026-09-04 原话转述）：①图表维度少 ②有空图表/错误图表（bug）③Plan 执行过程可见+默认折叠。全部追到根因、红→绿修复，请验证。

Review-Target-ID: f002-g17
Branch: feat/f002-g17-chart-quality（head 4258fe8 / 代码 2ce22b0）

## Original Requirements（愿景验证用）

铲屎官 2026-09-04 于 thread `thread_mtli5iy7idx36e5m` 原话（球经奉孝 403 中断后转法正）：

> ①图表维度少 ②有空图表/错误图表 ③Plan 执行过程要可见、默认折叠

请对照判断：修复 1 是否回应①+②、修复 2 是否回应③、清理 3 是否堵住②的污染源。

## Architecture Ownership（F191）

- Architecture cell: atomic-visualizer（既有）/ web-rendering（既有）/ flow-promotion（既有，本 PR 仅加护栏测试，不改语义）
- Map delta: none
- Why: 全部在既有边界内——visualizer 修 y 契约消费方式、web 加只读展示、promoter 行为不变仅固化回归契约。无新 Store/Router/Adapter/Dispatcher。

## What

### 修复 1：visualizer `y=list` 逐列展开多 trace（需求② 空图/错图 + 需求① 维度少）

- **根因（实测复现）**：`model.aggregate` 恒产出 `ChartSpec.y = list(agg.keys())`——**哪怕单指标也是单元素 list**。旧 `visualizer.py` 直接 `go.Bar(x=df[spec.x], y=df[spec.y])`，`df[列表]` 返回 DataFrame，plotly 收到 2D 嵌套数组（实测 `[[50],[20],[30]]`）→ **A 轨冷启动模板（品类对比/TopN，单指标 agg）天天出空图/畸形图**。多指标 aggregate 时更只画一个错 trace（=铲屎官说的"维度少"）。
- **修法**（`atomic/visualizer.py`）：bar/line 的 y 经 `_y_cols()` 归一化为列列表后逐列展开 trace——单列 → 1 扁平 trace（Series，保持旧契约），多列 → N 个命名 trace（图例可读）。`max_rows` 采样对每个 trace 生效。
- 4 红测试钉死行为（ndim=1 断言 / trace 数 / trace 命名 / max_rows 交互）。

### 修复 2：web「🔍 执行过程」默认折叠 expander（需求③）

- **根因**：`result.log`（executor 每步 op/成败/错误/chart 类型）此前**完全没渲染**，结果区只有 `执行步骤 2/3` 一个数字。
- **修法**（`web/app.py`）：纯函数 `_format_run_log` 渲染 markdown 步骤表（每步序号+✅/❌+op+摘要：成功取 report 关键字段、model 步显示"→ 产出 X 图"、失败显示错误原因），挂 `st.expander("🔍 执行过程（N/M 步成功）", expanded=False)`——默认折叠不打扰，点开全见。3 红测试。

### 清理 3：fake 污染产物删除 + 断根护栏（需求② 错误图表的源头之一）

- **根因链（runs.jsonl + 文件时间戳实锤）**：FakePlanGenerator 产物（plan_id 恒 `fake-` 前缀，ai/fake.py:45）经 fallback 落盘 → 同 (fp,intent) 请求 B 轨复用凑满 ≥3 成功 → `scan_and_promote` 晋升 → `tpl-fake-da4d81cc-趋势分析.yaml` 写进**包内置模板库**。intent=趋势分析、steps=aggregate → 用户问"趋势"命中它出**错图**（名不副实）。且 fake 的"趋势分析无 datetime 列退化 aggregate"（fake.py:134-140）本是测试兜底逻辑，晋升成用户资产后语义漂移。
- **已删**：`tpl-fake-da4d81cc-趋势分析.yaml` + `plans/fake-da4d81cc.json`（均 gitignored 的本机运行时残留，从未进 git；归档 `review-notes/quarantine-2026-09-04/`）。`runs/runs.jsonl` 5 条 fake 历史行**保留**（事实记录不篡改）。
- **护栏测试**（2 用例）：源 Plan 已删时 `promote/scan_and_promote` 不得从残留 run 记录复活晋升——保证清理持久有效。**真实库实测** `scan_and_promote() == []`，templates 回到 3 个冷启动。

## Why / Tradeoff

- **promoter 晋升门槛（≥3 全 0 分 run 可晋升，无 user_adopted 要求）不改**：spec §7.3 原意如此；收紧是产品语义变更，已记 BACKLOG 候选，待铲屎官拍板（见 Open Questions）。
- **测试 Fake 污染包库的根治（tmp store fixture / CLI 默认库改用户目录）不在本 PR**：属测试卫生/CLI 设计变更，与图表质量正交；已记 BACKLOG。
- **`_format_run_log` 是纯函数**：与 web 渲染解耦，可单测（本仓 web 测试风格即纯函数级，无 AppTest）。

## Evidence

- TDD 红→绿：新增 **9 用例**（visualizer 4 + web log 3 + promoter 护栏 2），红态输出亲见（ndim=2 实测值 / trace 数 1≠2）
- 全量：**286 passed, 0 failed, 5 skipped**（基线 277 + 9 新用例，`PYTHONPATH=<worktree>/src` 隔离 editable 安装）
- Dogfood 端到端（真实 `run()` 链路，隔离 tmp 库）：fallback route / 3 步全 ✅ / 2 chart 产出；trace `y.ndim=1 pts=4`（旧代码此处必 2D 嵌套）；run_log markdown 渲染正确（✅/❌/失败原因全验）
- **UI 冒烟（Streamlit AppTest）**：`at.exception=[]`、"🔍 执行过程" expander 存在、步骤表 markdown 含 op 名+✅+❌+KeyError 原因、`plotly_chart` 元素数=2（单指标 list y + 多指标 list y 均渲染成功）→ 前端需求③组件级实证
- ruff 基线 diff：HEAD~1 与 HEAD 错误数完全一致（20→20，全部既有债），**未引入新问题**
- compileall 语法门 exit=0

## Open Questions

1. **晋升门槛收紧候选**：`check_promote` 对"0 次人工采纳"的 plan 也放行（≥3 全成功即可）。建议候选：要求至少 1 次 `user_adopted=True` 才晋升。这是 spec §7.3 语义变更，我未动——你和铲屎官觉得该收吗？
2. **runs.jsonl 里 fake 的 5 条历史成功记录保留**：它们仍满足 count≥3，仅因源 plan 已删而不复活（护栏测试钉死）。若未来"重新生成同名 plan"会立即复活晋升——plan_id 含 uuid 碰撞概率≈0，我判断可接受。有异议标出。

## Next Action

关羽 review → 放行后走 merge-gate 合入 main。BACKLOG/Timeline 同步随本分支 docs commit。

[法正/Qwen3.8-Flash🐾]
