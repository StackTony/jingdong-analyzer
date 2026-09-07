---
topics: [review-request, f002, g19]
feature_ids: [F002]
doc_kind: review-note
created: 2026-09-07
---

# G19 Review 请求：流式 reasoning_content 透传（AI 思考过程真流式）

@关羽 请 review 分支 `feat/f002-g19-stream-reasoning`（commit 377fbc3，已推远端）。

## What

G18 合入后铲屎官实测反馈「流式输出还是没有在 web 界面显示」。
本分支定位根因并修复：**GLM 推理模型思考阶段 `delta.content` 全程为 None，
思考内容在 `delta.reasoning_content`**——G18 的 `chat_stream` 只透传 content，
思考期间（实测 5.9s-21.5s，占全程一半）web 占位区必然空白。

## 根因证据（裸 SDK 直测，非推理）

```
2.90s chunk0: delta=ChoiceDelta(content=None, reasoning_content='The')
2.94s chunk1: delta=ChoiceDelta(content=None, reasoning_content=' user')
...
21.5s 起 delta.content 才开始有值
```

## 改动面（6 文件，+264/-56）

| 层 | 文件 | 改动 |
|----|------|------|
| Provider | `llm_provider.py` | `chat_stream` 契约升级：yield `(kind, text)`——`'reasoning'`/`'content'` 双 kind；base 默认回落 yield `('content', chat()全文)`；标准 OpenAI delta 无 reasoning_content 字段时 getattr 兜底 None |
| Reviewer | `llm_reviewer.py` | `on_delta(kind, chunk)` 双参回调，思考段+正文段都通知；**返回值仍只含正文**（reasoning 不混入报告文本，save_run 沉淀不变） |
| base | `base.py` | `review_stream` 默认回落同步 `on_delta("content", full)` |
| web | `app.py` | 双区流式渲染：思考区（灰色引用块「AI 思考中…」+ 逐块滚动）+ 正文区，各自节流 8 chunk；**结束时定格 flush**（修 G18 短报告 <8 chunk 不刷新边缘）+ 清思考区 |
| 测试 | `test_g19_reasoning_stream.py` 新 6 用例 + `test_g18_streaming.py` 契约迁移 | 详见下 |

## 连调实测（真实网关 GLM-5.3-Flash，reviewer 全链路）

- reasoning 首块 **5.9s** 到达（737 块，5.9-21.5s 持续流入）
- content 21.5s 起流入（680 块），40.4s 完成
- 旧版此期间用户只见"AI 分析中"死文字；现在 5.9s 起思考过程可见

## Why This Design

- **契约从 str 升级 (kind, str)**：思考 token 与正文必须可区分（渲染样式不同、
  reasoning 不进报告正文）。一步到位，避免后面加第二通道的破坏性变更。
- **返回值只含 content**：review 文本要 save_run 沉淀、dashboard 统计，
  reasoning 混入会污染存量数据结构。
- **结束时定格 flush**：`_flush_stream()` 在 run 返回后无条件再刷一次，
  <8 chunk 的短流也能显示（G18 review 记录 2 的边缘修复）。

## Tradeoff / 已知边界

- reasoning 展示只在运行 session 内（rerun 后消失，不持久化）——
  思考过程是过程性信息，不进 RunRecord。
- G18 测试断言全部迁移新契约（单参回调→双参、裸 str→tuple），
  这是接口升级的预期破坏，非回归。
- MagicMock 坑：delta 未显式设 `reasoning_content=None` 时 auto-mock
  是 truthy，会把无 reasoning 的 chunk 误判为有——测试里全部显式置 None。

## Test Evidence

- TDD 红绿：`test_g19_reasoning_stream.py` 6 用例（provider 三态 / reviewer
  双段流 / run 转发），先红后绿。
- G18 契约迁移：`test_g18_streaming.py` 断言更新，行为语义不变。
- 全量：`PYTHONPATH=src python -m pytest tests -q` → **312 passed, 5 skipped**
  （基线 306 + 6 新增，无回归）。
- 真实网关连调：如上（40.4s 全程，5.9s 首可见）。

## Open Questions

1. 节流阈值仍是 8——现在 reasoning 流块很密（737 块/16s），体感待铲屎官
   验收；过密可降到 4。
2. 思考区用 blockquote 渲染长思考（737 块拼接）可能很长，是否要加
   max-height 滚动容器（Streamlit `st.container(height=...)`）——
   铲屎官验收时看观感再定。

## Next Action

关羽 review 通过 → merge-gate 合入 → 铲屎官浏览器验收流式体感。

[奉孝/GLM-5.3🐾]
