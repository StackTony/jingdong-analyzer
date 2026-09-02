---
feature_ids: [F002]
review_target_id: f002
branch: feat/f002-analytics-framework
head_sha: 1c9d8354b1f54aa049f502a4a9aaad6cf99e7135
author: 郭嘉/奉孝 (@ragdoll-pa82, ragdoll-pa82 family)
reviewer: 关羽/云长 (@cat-ko094z1n, cat-ko094z1n family / 缅因猫)
created: 2026-08-31
doc_kind: review-request
---

# F002 合入主干前 Review 请求

@云长

F002 通用数据分析框架 P1–P6 + 真实 LLM 接入迭代完成，准备合入主干。
铲屎官指令："先合并到主干吧"（06:21 UTC）。按 merge-gate 铁律 2，跨家族 review 是硬约束——你是本 spec 标注的 code reviewer，请审查。

## 原始需求（Reviewer 请对照判断）

来源：`docs/features/F002-universal-analytics-framework.md` (spec, owner: 荀彧/文若)

铲屎官原话（spec §Why）：
> "要做的不只是'分析京东品类数据'，而是一个**能反复用、跨数据源、AI 辅助、且能在使用中自进化、节省 token 消耗**的通用分析框架。"
> "直接痛点：数据分析流程高度固定（同类问题反复出现），但每次让 LLM 重新推理 = token 浪费"
> "需要'流程固定但能自进化'——既要命中已知流程走捷径（省 token），又要能处理新场景并沉淀"

方案 C：双轨自进化（A 模板库 + B Plan 库 + 晋升通道 B→A）。
铲屎官 2026-08-31 拍板（"通用框架 + 自进化 + 省 token"）。

Phase 路线图（spec §11）：
- P1: DataSource Adapter + 原子能力集骨架 + Dataset 抽象 (AC-1,2)
- P2: Orchestrator + Flow Library + 单轨 B (AC-4,6,11)
- P3: AI Plan 生成器 + Reviewer (AC-3,5,7)
- P4: A 轨模板 + 晋升机制 + 仪表盘 (AC-5,10,12)
- P5: CLI + Streamlit 面板 (AC-8,9)
- P6: ≥3 冷启动模板 + 命中率观测 (AC-10,12)

本轮迭代额外接入真实 LLM（csi provider / GLM-5.2），替换 P3 的 Fake 实现。

## Architecture Ownership (F191)

- **Architecture cell**: F002 是新独立 cell——`clowder_analytics` 包，与 F001 `jd_analytics` 物理隔离（spec D5 决策）。模块视图见 spec §2：DataSource Adapter / Cleaner / Modeler / Visualizer / AI Reviewer / Orchestrator / Flow Library 七模块。
- **Map delta**: new cell required（F002 是新 feature，新增独立包 `src/clowder_analytics/`，不侵蚀 F001）
- **Why**: F001 强绑京东语义（SPU/SKU/评价数差值），F002 要通用跨数据源。物理隔离避免口径侵蚀；F001 后期可作为 F002 的 use case。

请 Reviewer 检查：diff 是否与"new cell required"一致？有没有偷偷改 F001 的代码或共享契约？

## 自检证据

### 门禁前置
- 工作树干净（`git status --porcelain` 空）✓
- 根目录工件闸门：`git diff --name-only origin/main...HEAD` 无根目录媒体/设计工件 ✓
- 与 origin/main 同步：merge-base = origin/main HEAD (7a825b4)，0 commits behind，无需 rebase ✓

### 测试
- 命令：`python -m pytest tests/ --ignore=tests/test_llm_smoke.py -q`
- 结果：**208 passed, 1 skipped**（skip = sklearn 未装时 cluster 跳过）
- 真实 LLM 烟测（手动跑，需 CSI_API_KEY）：4 passed，csi provider 连通 + Plan 生成 args 对齐 op_spec + Reviewer 三段式报告 ✓

### Scope
- 11 commits, 63 files changed, +6852/-1 lines
- 全部在 `src/clowder_analytics/` + `tests/` + `docs/features/F002-*.md` + `pyproject.toml` + `README.md`
- 不触碰 F001 任何代码 ✓

## 改动总览（11 commits）

```
1c9d835 feat(F002): 真实 LLM 接入 - GLM-5.2 via csi provider
0f58543 test(F002): 修 P6 后 test_cli_run_csv_topn 期望
0b5af16 feat(F002): P6 3 个冷启动模板 + 仪表盘 + 通配匹配
295f923 feat(F002): P5 CLI + Streamlit 面板
c3cbb7e feat(F002): P4 晋升/降级机制 + 端到端 run() 入口
4534d8d feat(F002): P3 AI Plan 生成器 + Reviewer 接口与 Fake 实现
df6c7fa feat(F002): P2 Flow Library + Router 双轨 + 意图分类
35fb45d feat(F002): P1.5 Plan 执行器 - 固定 Plan 端到端跑通
25304cc feat(F002): P1 Modeler 6 op + Visualizer 4 类图表 + ChartSpec
b425607 feat(F002): P1 Excel/CSV/SQLite Adapter + 6 Cleaner 原子 op
6d08502 feat(F002): P1 启动 - 架构 ADR + 包骨架 + Dataset 抽象 TDD 通过
```

详见 `git diff origin/main...HEAD`。

## 重点审查建议

请把时间花在这些点上（不要在基础检查上）：

1. **op_spec.py args schema 注入是否真堵住 LLM 自创字段名**（P3+ 关键修复）
   - `src/clowder_analytics/atomic/op_spec.py` — 12 op 的 args schema 集中定义
   - `src/clowder_analytics/ai/llm_plan_generator.py` — `format_op_specs_for_llm()` 注入 prompt
   - 真实 LLM 实测：生成 args 字段名完全对齐（columns/group_by/value_col/n），不再出现 fields/dimensions
   - 请检查：OP_SPECS 字段名是否与真实 op 函数签名一致？（`tests/test_llm.py::test_op_specs_field_names_match_real_signatures` 已覆盖抽样）

2. **双轨自进化闭环是否真闭环**（P4 核心价值）
   - `src/clowder_analytics/orchestrator/router.py` — A→B→fallback 路由
   - `src/clowder_analytics/orchestrator/run.py` — 端到端入口 + promote 调用
   - `src/clowder_analytics/flow_library/promoter.py` — B→A 晋升（N=3 + 成功率≥80%）
   - 请检查：fallback 路径是否复用 existing plan（同 fp+intent）避免每次新 uuid 导致永远不满足"同 plan_id 3 次"？

3. **LLM 安全边界**
   - `src/clowder_analytics/config/ai_providers.yaml` — apiKey 走 `CSI_API_KEY` 环境变量，不入库 ✓
   - `src/clowder_analytics/ai/llm_provider.py` — `load_provider` 缺 env var 时 raise RuntimeError
   - 请检查：有没有偷偷把 apiKey 硬编码？yaml 里只有 `api_key_env: CSI_API_KEY`

4. **JSON 容错解析**（LLM 输出不稳定）
   - `llm_plan_generator.py::_parse_json` — 去 markdown fence + 找首{末}
   - `_call_with_retry` — JSON 校验失败重试一次（spec §5.1）
   - 请检查：容错是否过度宽容导致 silent failure？重试是否真能触发？

## Open Questions

### 技术 OQ（给 Reviewer）
- OQ-1: `op_spec.py` 的 args schema 是手写维护的（与 op 函数签名分离）。是否应该用 pydantic / introspect 自动同步避免漂移？MVP 阶段手写 + 抽样测试是否够？
- OQ-2: `promoter.py` 的晋升条件 N=3 + 80% 成功率——冷启动阶段无足够样本，这个阈值是否需要动态调整？还是先硬编码 MVP 跑起来再调？
- OQ-3: `llm_provider.py` 用 `openai` SDK 调 csi 的 OpenAI-compatible endpoint。GLM-5.2 是推理模型，max_tokens=4000 留 reasoning_tokens 空间——这个值是否合理？实测 content 偶尔为空（reasoning_tokens 吃光），不抛异常算连通。是否应该更严格？

### 价值 OQ（需 CVO 判断，附 Decision Packet）
- 无。所有决策点已在 spec §12 (D1-D8) 列出并选定倾向，铲屎官已拍板"通用框架 + 自进化 + 省 token"。本轮实现忠实执行 spec，无新增愿景级决策。

## Review-Target-ID

```
Review-Target-ID: f002
Branch: feat/f002-analytics-framework
HEAD: 1c9d8354b1f54aa049f502a4a9aaad6cf99e7135
```

Reviewer 沙盒标准路径（如需）：`/tmp/cat-cafe-review/f002/guanyu`
但本项目是 Python（无 pnpm review:start），reviewer 可直接在 worktree 跑：
```bash
cd <repo-root>
git fetch origin
git checkout feat/f002-analytics-framework
python -m pytest tests/ --ignore=tests/test_llm_smoke.py -q
```

## 阻塞点（需铲屎官知晓）

1. **`gh` CLI 未安装**：merge-gate Step 3 (开 PR) / Step 5 (触发云端 review) / Step 7 (squash merge) 都依赖 `gh`。本机 Windows 环境无 gh。需铲屎官决定：
   - (a) 安装 gh CLI 后我继续走完整 merge-gate
   - (b) 铲屎官在 GitHub web 手动开 PR + squash merge，我做本地清理
   - (c) 跳过云端 review（docs/code 混合 PR，有代码改动按规则不能豁免）

2. **cat-cafe MCP 工具未暴露**：本会话无 `cat_cafe_post_message` / `cat_cafe_cross_post_message` 等工具。我通过 HTTP API (`POST http://127.0.0.1:3004/api/messages`) 投递本请求信到关羽。如通道异常请告知。

## 下一步

请 Reviewer 回复：
- **放行**（"放行"/"LGTM"/"通过"/"可以合入"）→ 我继续 merge-gate Step 3+
- **踢回**（带 P1/P2 findings）→ 我修完重发 review 请求

[奉孝/GLM-5.2🐾]
