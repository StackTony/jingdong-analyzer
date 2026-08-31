---
feature_ids: [F002]
related_features: [F001]
topics: [adr, architecture, f002, decisions]
doc_kind: adr
created: 2026-08-31
owner: 郭嘉/奉孝 (@ragdoll-pa82)
status: approved
spec_ref: docs/superpowers/specs/2026-08-31-通用数据分析框架-design.md
---

# ADR-0001: F002 架构决策（D1-D8 奉孝 review 立场）

> Owner: 奉孝 (@ragdoll-pa82) | Date: 2026-08-31
> Spec: docs/superpowers/specs/2026-08-31-通用数据分析框架-design.md §12
> 上游：文若 (@cat-rp3g6qqr) 起草 spec，标 8 个"待奉孝对撞"决策点
> 铲屎官 2026-08-31 03:14 指令"按 spec 内容实现"——本 ADR 是实现前的架构 review 沉淀。

## 总判断

✅ **spec 整体设计扎实**——双轨 + 晋升 + 降级 + 运行日志 + 风险登记覆盖到位。8 个待决策点我同意 6 个、调整 2 个、新增 2 个。

---

## D1: A 轨模板载体格式

**spec 倾向**：YAML 声明式 + 嵌入式参数
**奉孝立场**：✅ **同意**

理由：
- YAML 可 diff 可版本化，code review 友好
- LLM 可直接生成（JSON 也行，YAML 更可读）
- 嵌入代码会破坏"知识资产"与"运行时"分离原则

补充约束：YAML 模板内**不允许嵌入任意 Python 表达式**（jinja2 只做参数替换，不做逻辑）——避免 LLM 生成的模板变成代码注入向量。

---

## D2: B 轨 Plan 检索机制

**spec 倾向**：规则指纹（schema hash + 意图关键词）起步，后期升级向量
**奉孝立场**：✅ **同意** + 补充**指纹要带语义层级**

调整：spec §3.4 的 fingerprint 只用 (列名, dtype)。我建议加 **semantic_hint 层**（spec §3.1 ColumnSpec 已有这个字段）—— 同名不同义列（如 "id" 在不同源语义不同）能靠 hint 区分。fingerprint 算法：

```python
def compute_fingerprint(df, column_hints: dict = None) -> str:
    # 基础层：列名+dtype（spec 原方案）
    base = sorted((c.lower(), str(df[c].dtype)) for c in df.columns)
    # 语义层：用户/LLM 声明的 hint（可选）
    hints = sorted((k, v) for k, v in (column_hints or {}).items())
    return sha256(json.dumps({"base": base, "hints": hints}).encode()).hexdigest()[:16]
```

匹配时先 exact base+hints，base 兜底走 column_hints 字段映射（spec §7.2 已有此机制，跟我的调整一致）。

---

## D3: 晋升条件 N 值

**spec 倾向**：N=3 + 人工审核门槛（candidate → stable）
**奉孝立场**：✅ **同意**，但加一条**失败率上限**

补充条件：
- spec 原条件：命中 ≥ 3 次 + 成功率 ≥ 80% + 无人工修正
- 我加：**且无 OpError 类失败**（区分"用户拒绝采纳" vs "执行报错"——前者是 Plan 不合适，后者是 Plan 有 bug，bug 类失败一次就该 review）

N=3 + 80% + 0 OpError 失败 → 自动入 candidate → 人工审核 → stable。

---

## D4: schema 指纹算法

**spec 倾向**：列名小写归一 + dtype hash
**奉孝立场**：见 D2 调整（加 semantic_hint 层）

---

## D5: 与 F001 代码包名冲突处理 ⚠️ 关键

**spec 倾向**：F002 独立包名 `jd_analytics_framework`（或 `clowder_analytics`）
**奉孝立场**：✅ **同意独立包**，但包名选 **`clowder_analytics`** 而非 `jd_analytics_framework`

理由：
- spec §10 R10 明确"通用框架不能被京东语义侵蚀"——包名带 jd 是泄漏
- `clowder_analytics` 体现"家里通用能力"定位，跟家里其他工具（cat-cafe-* / clowder-*）命名一致
- 后续 F001 的京东分析可作为 `clowder_analytics` 的 **use case**，通过 DataSource Adapter 接 jd_analytics.db 或导出 Excel，**不直接 import F001 业务模块**

落地形态：
```
src/clowder_analytics/      # F002 通用框架包
src/jd_analytics/          # F001 京东业务（既有，不动）
pyproject.toml             # 双包共存（src layout）
```

pyproject.toml 加 `[tool.setuptools.packages.find] where = ["src"]`，两个包都能 install。

---

## D6: AI Reviewer 默认 LLM

**spec 倾向**：可配置 + 默认 GLM-4.6
**奉孝立场**：✅ **同意**

补充：`config/ai_providers.yaml` 应支持**家里 model 优先级**：
1. GLM-4.6（家里默认，省跨家成本）
2. Claude（如果家里有 API key，Plan 生成质量更好）
3. OpenAI（备选）

实现时**用 anthropic SDK 统一接口**（claude-api skill 已有 pattern），通过 provider adapter 切换。不要直接绑死 zhipu SDK——后期换 model 不改业务代码。

---

## D7: MVP 是否支持 Plan 分支/循环

**spec 倾向**：MVP 不支持（Plan 是线性 step 列表）
**奉孝立场**：✅ **同意**

理由：MVP 复杂度控制是正确的。复杂场景走兜底 LLM 直接推理。**但 Plan schema 要预留扩展位**：

```json
{
  "steps": [...],
  "branches": null  // MVP 留 null，P5+ 可扩展
}
```

避免后期改 schema 破坏已沉淀的 Plan。

---

## D8: 持久化目录是否单独 repo

**spec 倾向**：`flow_library_data/` gitignored，单独 repo 或子目录
**奉孝立场**：🟡 **调整为"跟随主 repo 入库"**

理由：
- spec 阶段说"知识资产长期会膨胀"——但 MVP 阶段模板/Plan 数量有限（< 50 个），膨胀是远期问题
- 单独 repo 增加协作摩擦（PR 流程 + 同步成本），MVP 不值
- 入库反而让 review 流程顺（code review PR 时能看模板 diff）
- 后期真的膨胀了（> 200 模板）再 split，git filter-repo 能拆

落地：
- `flow_library_data/templates/` 和 `plans/` 入库（知识资产，可 review）
- `flow_library_data/runs/` gitignored（运行日志是用户私有数据，不入库）

---

## 新增 D9: spec 文件路径规范化

**问题**：spec 在 `docs/superpowers/specs/2026-08-31-通用数据分析框架-design.md`——这是 superpowers skill 的产出路径，不符合项目惯例 `docs/features/Fxxx-*.md`。

**奉孝立场**：**保留原路径 + 在 docs/features/ 加软链接**

理由：
- 原路径保留 superpowers 产出上下文（可还原"是哪只猫用哪个 skill 在什么时候产出的"）
- 项目惯例 `docs/features/F002-*.md` 用于 BACKLOG 索引
- 软链接兼顾两者

落地：
```bash
# 在 worktree 里
ln -s ../superpowers/specs/2026-08-31-通用数据分析框架-design.md docs/features/F002-universal-analytics-framework.md
```

---

## 新增 D10: Phase 实施顺序微调

**spec 原序**：P1（骨架）→ P2（Orchestrator+B轨）→ P3（AI）→ P4（A轨+晋升）→ P5（CLI+Streamlit）→ P6（冷启动+观测）

**奉孝立场**：🟡 **调整为 P1.5 测试前置**

理由：spec AC 里有"原子能力集 16 个 op + 4 类 visualizer"，每个 op 是纯函数——**TDD 友好**。P1 实现时每个 op **先写红测再写实现**（superpowers:test-driven-development skill 已加载，用起来）。

调整后顺序：
- P1：Dataset + Adapter + 原子 op（**每个 op 红→绿**）
- P1.5：Plan 执行器（用 P1 op 跑通一个固定 Plan，无 LLM）
- P2：Flow Library + B 轨 Plan 存储 + Router（仍不调 LLM）
- P3：AI Plan 生成器 + Reviewer
- P4：A 轨模板 + 晋升
- P5：CLI + Streamlit
- P6：冷启动 + 观测

P1.5 的价值：在调 LLM 前先验证"Plan + op + 执行器"链路通——避免 P3 接 LLM 后调试链路问题叠加 LLM 问题。

---

## 实施计划

按 spec §11 Phase 路线 + 本 ADR 调整后顺序推进：

| Phase | 状态 | 产出 |
|-------|------|------|
| ADR（本文件） | ✅ 完成 | D1-D10 决策沉淀 |
| P1 | 进行中 | Dataset + 4 Adapter + 16 原子 op（TDD） |
| P1.5 | 待开始 | Plan 执行器 + 固定 Plan 端到端 |
| P2 | 待开始 | Flow Library + Router B 轨 |
| P3 | 待开始 | AI Plan 生成器 + Reviewer |
| P4 | 待开始 | A 轨模板 + 晋升机制 |
| P5 | 待开始 | CLI + Streamlit |
| P6 | 待开始 | 3 个冷启动模板 + 仪表盘 |

## 待与文若对齐

本 ADR 是奉孝单方面 review 立场。按 F167 L2 并行模式规则，文若串行轮会看到本文件并给反馈。**对齐点**：

1. D5 包名选 `clowder_analytics`（vs spec 倾向 `jd_analytics_framework`）—— 这是最关键的分歧
2. D8 持久化目录入主 repo（vs spec 倾向独立 repo）
3. D9 spec 路径软链接（spec 没提）
4. D10 加 P1.5 测试前置（spec 没提）

如文若对 D5/D8 有强反对意见，回退到 spec 原方案，本 ADR 修订。否则按本 ADR 落地。

## 后续

按 spec §"后续"段：本 ADR + spec 经铲屎官确认后开始 P1 实现。铲屎官已 03:14 拍板"按 spec 实现"，本 ADR 视为实施前 review，直接进 P1。
