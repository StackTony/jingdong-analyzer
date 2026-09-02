---
feature_ids: [F002]
review_target_id: f002
branch: feat/f002-analytics-framework
head_sha_at_request: 1c9d8354b1f54aa049f502a4a9aaad6cf99e7135
reviewer: 关羽/云长 (@cat-ko094z1n)
verdict: 放行 (LGTM)
verdict_time: 2026-08-31 06:43 UTC
doc_kind: review-verdict
---

# F002 Review 结论 — 关羽放行

@云长 回复结论：**放行（LGTM）**，可合入主干。

## 核心审查 6 项全通过

1. **op_spec args schema 堵 LLM 自创字段** ✓ — 12 op 签名逐个核对，字段名一致；`format_op_specs_for_llm()` L68 注入 prompt，L106-108 明示严格按 args schema
2. **双轨自进化闭环** ✓ — router A→B→fallback + run.py fallback 生成后 save_plan + promoter check_promote(N=3+80%)/promote 幂等/check_and_demote(连续5失败)/scan_and_promote 全实现
3. **LLM 安全边界** ✓ — yaml 只写 `api_key_env`，llm_provider L147-153 从 env 读，无硬编码
4. **JSON 容错解析** ✓ — `_parse_json` 去 fence + 找首{末}；`_call_with_retry` 重试 + max_retries=2 上限 + RuntimeError
5. **测试** ✓ — worktree 实跑 208 passed + 1 skipped，与自检一致
6. **Scope / 架构 cell** ✓ — 63 files 全在 clowder_analytics + tests + docs，未触碰 F001

## P2 findings（不阻塞合入，记 BACKLOG 后续修）

> 关羽明确标注"不阻塞合入，建议后续 fix"。按 merge-gate，reviewer 把 P2 降级 P3 留后续 = 接受放行，不需现在修触发 SHA 变化。

### P2-1: `llm_plan_generator.py:124` max_tokens=2000 硬编码覆盖 yaml 4000

- **现状**：`_call_with_retry` 调 `provider.chat(..., max_tokens=2000)` 硬编码 2000
- **yaml 意图**：`ai_providers.yaml:23` 写 `max_tokens: 4000`（留 reasoning_tokens 空间）
- **影响**：实测 2000 够用（208 测试 + 4 烟测 passed），但配置意图被忽略 = 维护性 bug
- **修法**：`_call_with_retry` 不传 max_tokens 让 provider 用 ProviderConfig 默认（从 yaml 读），或显式 `self.provider.config.max_tokens`
- **跟进**：P7+ 修，单独 PR

### P2-2: `promoter.py:159` scan_and_promote 过滤 `route=="B"` 与 run.py per-run promote 不一致

- **现状**：run.py L139 per-run promote 不区分 route；scan_and_promote L159 只扫 `route=="B"`，漏 fallback 路径
- **实际闭环通**：fallback 生成的 plan save 后，下次同 (fp, intent) 走 B 轨（router L72 命中），scan_and_promote 兜底能覆盖
- **漏的场景**："只调 library.save_run 不调 run()" 的场景会漏
- **修法**：scan_and_promote L159 去掉 `r.route == "B"` 过滤（spec §7.3 路径1"命中执行 ≥ N 次"不区分路由）
- **跟进**：P7+ 修，单独 PR

### P2-3: `run.py:99-102` "复用 existing plan" 分支是死代码

- **现状**：router L72 已调 match_plan 判 B 轨未命中（否则不走 fallback），run L99 再调 match_plan 必然 None
- **不影响功能**：fallback 第一次生成 save，第二次走 B 轨，"避免每次新 uuid"靠 save_plan + 下次 B 命中实现
- **修法**：删 L99-102 死代码，或加注释说明防御性
- **跟进**：P7+ 修，单独 PR

## OQ 回复（关羽）

- **OQ-1**（op_spec 手写 vs pydantic）：MVP 手写 + 抽样测试够。漂移风险可控（12 op 数量小，每加 op 时 review 强制核对）。P7+ 再上 pydantic。
- **OQ-2**（晋升 N=3 冷启动）：硬编码 MVP 跑起来再调。spec §7.3 留"拟，待奉孝对撞"标注 = 待验证假设。观察首批晋升 plan 质量后再调。
- **OQ-3**（max_tokens=4000 是否合理）：见 P2-1，代码实际是 2000 不是 4000。建议改读 ProviderConfig.max_tokens 让 yaml 配置生效。reasoning_tokens 吃光 content 为空时建议加日志记录便于排查（当前空 content 会触发 `_parse_json` ValueError 走重试，逻辑对，但缺日志）。

## Review Continuity Guard 状态

- Reviewer 放行对应 SHA = `1c9d835`（请求时的 HEAD）
- 当前 HEAD = `1c9d835`（未变）
- ✓ 放行覆盖当前 HEAD，通过 Continuity Guard

## 后续 merge-gate 阻塞

仍卡在 gh CLI 未安装（Step 3+ 无法本地执行）。等 @co-creator 拍板 (a) 装 gh / (b) web 手动 / (c) 跳过云端 review。

[奉孝/GLM-5.2🐾]
