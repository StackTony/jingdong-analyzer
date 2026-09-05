---
topics: [review-request, f002, g18]
feature_ids: [F002]
doc_kind: review-note
created: 2026-09-05
---

# G18 Review 请求：执行过程增强 + AI Reviewer 流式输出

@关羽 请 review 分支 `feat/f002-g18`（commit 1a14f1b，已推远端）。

## What

铲屎官 2026-09-05 反馈两点，本分支一次修完：

1. **「命中模板的执行过程还是输出太少」**——G17 的 `_step_detail` 只显示
   ✅/❌ + op 名 + chart type，看不到每步用了哪些列、数据形态变化。
2. **「AI reviewer 的思考过程也可以展示出来，可以流式输出，不然用户一直在等待」**
   ——reviewer 是阻塞调用，真实 LLM 生成报告期间用户只看到"分析中"死等。

## 改动面（8 文件，+583/-14）

### A. 执行过程增强

| 文件 | 改动 |
|------|------|
| `orchestrator/executor.py` | entry 增加 `args`（dict 拷贝）+ `shape_before`/`shape_after`（tuple）；model 步 report 扩为 `{chart_spec, title, x, y}` |
| `web/app.py` | `_step_detail` 渲染 args（值截断 24 字符）+ shape 变化（`33万行 → 20行`）+ chart 维度；新增 `_shape_bits`/`_args_bits` 辅助；旧格式 entry 向后兼容 |

### B. 流式 reviewer（三层链路，每层非流式回落）

| 层 | 文件 | 设计 |
|----|------|------|
| Provider | `ai/llm_provider.py` | `LLMProvider.chat_stream` base 默认回落 `chat()` 一次性 yield（generator 函数）；`OpenAICompatibleProvider` 覆写用 `stream=True`，空 delta chunk 跳过 |
| Reviewer | `ai/base.py` + `ai/llm_reviewer.py` | `AIReviewer.review_stream(on_delta)` base 回落 `review()`；LLMReviewer 复用 `_build_user_prompt`（prompt 与 review() 完全同构）流式累积 |
| run | `orchestrator/run.py` | `run(on_review_delta=...)` 可选参数，转发 review_stream；不传走原 review() 路径（零行为变化） |
| web | `web/app.py` | `st.empty()` 占位 + delta 节流（~8 chunk 一次）`markdown` 增量刷新；运行结束 `empty()` 清占位（结果区有正式渲染，避免重复） |

## Why This Design

- **base 默认回落**：Fake/Mock provider、test 里所有 legacy reviewer 零改动，
  流式是渐进增强不是破坏性变更。抽象类加非抽象方法不破坏现有子类。
- **args 用 `dict(step.args)` 拷贝**：防 op 内部改 args 污染 log。
- **web 节流 8 chunk**：Streamlit `st.empty().markdown()` 全量重渲染，
  每 chunk 刷一次会卡；8 chunk 粒度人眼仍是"流式"感知。
- **shape 记 tuple**：JSON 序列化后变 list，`_shape_bits` 里用 `tuple(...)` 归一。

## Tradeoff / 已知边界

- 流式渲染只在运行按钮触发的 session 内可见（Streamlit rerun 后消失，
  结果区有完整 review 文本兜底）。
- `_args_bits` 对 dict 值（如 `agg: {"sales": "sum"}`）显示 keys
  （`sales`），不显示聚合方式——完整 args 在 Flow Library / plan JSON 可查。
- reasoning 模型的思考 token（GLM reasoning_tokens）不透出，只有
  content delta 流式——思考过程=生成的报告文本。

## Test Evidence

- TDD 红绿：17 新用例（`test_g18_run_detail.py` 8 + `test_g18_streaming.py` 9），
  先红后绿。
- 全量：`PYTHONPATH=src python -m pytest tests -q` → **303 passed, 5 skipped**
  （基线 286 + 17 新增，无回归）。
- 覆盖：base 回落（provider/reviewer 两层）、OpenAI stream mock
  （chunk 拼接 + 空 delta 跳过 + kwargs 断言 stream=True）、run 转发
  （enable_review=False 不触发）、web 旧格式向后兼容。

## Open Questions

1. 节流阈值 8 是拍的，真实 LLM chunk 频率下体感待验证（连调时观察）。
2. `_tmp_lib_dir` 用了 tempfile.mkdtemp 不清理——测试量级可接受，
  review 时看是否要换 tmp_path fixture（我当时为绕开 fixture 作用域）。

## Next Action

关羽 review 通过 → merge-gate 合入 main → 真实 LLM 连调验证流式体感。

[奉孝/GLM-5.3🐾]
