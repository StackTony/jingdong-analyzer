---
feature_ids: [F002]
topics: [review, g16, flow-library, crud, ui]
doc_kind: note
created: 2026-09-03
author: 郭嘉/奉孝 (@ragdoll-pa82)
reviewer: 关羽/云长 (@cat-ko094z1n)
branch: feat/f002-g16-flow-ui
head: 8b79b3c
---

# G16 Flow Library 界面管理 — Review Request

@关羽 云长，G16 完成实现，请你跨家族 review。

## What

铲屎官需求（2026-09-03 原话）："当前工具没法手动界面查看更新和删除已有的 Plan 模板"。

- **store 层**（`flow_library/store.py`）：补 `delete_template` / `update_template` / `delete_plan` / `update_plan`。update 不新建（不存在抛 KeyError，防 update 静默变 create）；delete 不存在也抛 KeyError 不静默
- **web 层**（`web/app.py`）：新增顶层 tab「📚 Flow Library 管理」：
  - A 轨模板：元字段展示（stability / promoted_from / confidence）+ steps YAML 编辑保存 + 删除二次确认
  - B 轨 Plan：查看（steps JSON 展示）+ 删除二次确认
  - 二次确认用 session_state 确认状态机（点删除 → 红色警告 + 确认/取消两按钮）
- **元字段保护**（G16 验收点）：`_apply_template_edit` 从库中原模板回填 `promoted_from_plan_id` / `stability` / `confidence` / `fallback_strategy` / `created_at`，编辑表单不接触元字段，杜绝覆盖丢失
- **顺手修**：test_llm 隔离 bug——5 个 fixture 只 patch `_CONFIG_PATH` 不 patch `_LOCAL_CONFIG_PATH`，包内真实 `ai_providers.local.yaml` 深合并进测试配置污染 key。这正是主仓库基线 2 failed 的根因（昨天跑 G15 全量时未发现，今天现场发现）

## Why / Tradeoff

- update 复用 save_template 整体写入（不搞字段级 patch）：YAML 文件存储没有部分更新原语，整体写 + 从原值回填元字段是最简可靠方案
- Plan 不做 steps 编辑（只读 + 删除）：Plan 是 LLM 生成的复用产物，人工编辑意义小（模板才是晋升后的稳定资产）；需要改就晋升成模板再改
- main() 用 tab 重构而非加 sidebar 入口：管理页需要全宽展示 YAML 编辑器，sidebar 放不下

## Evidence

- TDD 红绿：新增 17 用例（CRUD 10 红→绿 + web 7 红→绿）
- 全量：**277 passed, 0 failed, 5 skipped**（基线 258+2failed → 修复 2 + 新增 17 = 277 全绿）
- UI 冒烟：Streamlit AppTest 跑通页面渲染无异常（4 tabs / 管理 selectbox 存在）

## Open Questions

1. `update_template` 元字段回填在 `_apply_template_edit`（web 层）而非 store 层——store 保持薄，编辑语义（哪些字段可编辑）属 UI 关注点。你觉得分层 OK 吗？
2. 删除模板后 `promoted_from_plan_id` 指向它的 Plan 不级联处理（Plan 保留）——我认为 Plan 独立生命周期，不级联；如觉得该级联请标出。

## Next Action

关羽 review → 放行后走 merge-gate 合入 main（流程同 G15）。

[奉孝/GLM-5.3🐾]
