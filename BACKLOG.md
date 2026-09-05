---
topics: [backlog]
doc_kind: note
created: 2026-08-25
---

# Feature Roadmap

> **Rules**: Only active Features (idea/spec/in-progress/review). Move to done after completion.
> Details in `docs/features/Fxxx-*.md`.

| ID | Name | Status | Owner | Link |
|----|------|--------|-------|------|
| F001 | 京东品类品牌销售数据采集 | **frozen**（2026-09-03 铲屎官拍板：后续不再演进） | 奉孝 | `docs/features/F001-jd-brand-analytics.md` |
| F002 | 通用数据分析框架（双轨自进化） | in-progress | 文若/奉孝 | `docs/features/F002-universal-analytics-framework.md` |

> **F001 冻结说明（2026-09-03）**：铲屎官拍板 F001 后续不演进。spec / 已有代码（京东爬虫栈、OCR 路线设计、RPA 行为模拟）保留存档不删除；登录墙 A/B/C 方案决策取消，Phase 0-4 路线图作废。F001 相关的复用价值已由 F002 的通用 DataSource Adapter（Excel/CSV/SQLite）承接。

## F002 合入后续（P7+ 候选）

> 关羽 review 标的 P2 findings（不阻塞合入，已合入 main 后跟进）+ AC-1 Postgres 缺口
> + 外部 AI review findings P1-P5（已处置）。

- [x] **P2-1 跟进**: `llm_plan_generator.py` max_tokens 已读 config（commit 122fc06 已修）；`llm_reviewer.py:40` 同模式硬编码 `max_tokens=2000` 已修（feat/f002-reviewer-max-tokens，读 `provider.config.max_tokens`，TDD 红绿 + 全量 211 passed 无回归）
- [x] **外部 AI P1**: 模板硬编码 sales/brand 列 → 列名变量化 `{{numeric_col}}` / `{{group_col}}` / `{{time_col}}` / `{{category_col}}`，`resolve_template_variables(tpl, ds)` 注入（feat/f002-review-fixes，TDD 红绿，218 passed）
- [x] **外部 AI P2**: FakePlanGenerator 趋势 Plan 用错时间列 → 新增 `_pick_time_col`，无 datetime 时退化到 aggregate（feat/f002-review-fixes，TDD 红绿）
- [x] **外部 AI P3**: 品类对比模板按 brand 聚合 → 改用 `{{category_col}}`，新增 `_pick_category_col` 偏好 category 列（feat/f002-review-fixes）
- [x] **外部 AI P4**: scan-promote 重复报告 → `scan_and_promote` 对比前后 templates 集合差，只返回新增（feat/f002-review-fixes，TDD 红绿）
- [x] **外部 AI P1-1 (B方案)**: ChartSpec.data 改 DataFrame 引用 + `to_json(max_rows=1000)` 惰性序列化，避免 33 万行 to_dict 占 +399MB 内存（feat/f002-chart-spec-arch，TDD 红绿，223 passed 无回归）
- [x] **外部 AI P1-2**: modeler.trend 内置 `pd.to_datetime` 预处理，字符串日期列自动转，无法解析抛 ValueError（feat/f002-chart-spec-arch）
- [x] **G1 大数据采样加载**: 3 个 adapter（CSV/Excel/SQLite）支持 `max_rows` 采样，CSV 用 `nrows`、Excel 用 `nrows` + openpyxl 流式数行、SQLite 用 `LIMIT N` 包 query；metadata 标 `sampled=True + full_row_count`（feat/f002-big-data-opt，TDD 红绿，231 passed 无回归）
- [x] **G2 render 大数据采样**: `render(chart_spec, mode, max_rows=N)` 新增 max_rows 参数，bar/line/scatter 用 `df.head(N)` 采样喂 plotly，heatmap 不采样（矩阵）；避免 33 万行 bar chart 全量序列化 JSON 卡浏览器（feat/f002-big-data-opt）
- [x] **G3 web app render 闭环**: 抽 `_render_chart(chart_spec)` 辅助函数，内置 `WEB_RENDER_MAX_ROWS=50` 默认采样，B 方案 `to_json` 闭环——web 端不再全量喂 plotly（feat/f002-big-data-opt）
- [x] **G13 通用 LLM 多 provider 多 model 对接**: `ai_providers.yaml` 新格式 `providers.<name>.models.<model_id>` map 结构 + `default_model` 字段；`load_provider(name, model)` 运行时选 provider 下任意 model；向后兼容老格式顶层 `model` 字段；新增 glm / euler-y 配置示例（feat/f002-llm-multi-provider，TDD 红绿，237 passed 无回归）
- [x] **G14 模型展示 + 切换 + api_key 直填**: `api_key` 直填字段（AI SDK 风格，优先于 `api_key_env`）；`list_providers()` 枚举 API；`get_default_provider_name()` 兜底；web sidebar Provider/Model selectbox + 当前模型展示（sidebar caption + 结果区 metric）；CLI `--llm-model` 参数；连通性实测 GLM-5.3-Flash/Qwen3.8-Flash 端到端通（feat/f002-model-switch，TDD 红绿，248 passed 无回归）。**P0 安全事故修正**：初版曾把真实 key 明文 commit 到公开仓库（关羽 review 发现），已止损——生产 yaml 改 `api_key_env: EULER_Y_API_KEY`、测试 fixture 换假 key、force-push 重写分支历史（c0322b6）
- [x] **G15 两层配置直填 key + 运行进度条**: `ai_providers.local.yaml`（gitignored `*.local.yaml`）深合并覆盖主配置，key 直填本地不入库；`api_key_env` 值校验（填成 `sk-` 开头当场报错，防 LL-049 现场误导报错）；`run()/execute()` 加 `progress(stage, current, total, detail)` 回调（向后兼容可选参数，回调异常双层兜底不反噬主流程），Web 端 `st.status` 分阶段容器 + execute 单进度条替代死转圈 spinner，CLI 端逐阶段打印 stderr（feat/f002-local-conf，TDD 红绿 6 新用例，258 passed 无回归，关羽跨家族 review 放行）
- [x] **G16 Plan/Template 界面管理**: Flow Library 的查看/更新/删除 UI（铲屎官 2026-09-03 提出"当前工具没法手动界面查看更新和删除已有的 Plan 模板"）。store 层 `delete/update_template` + `delete/update_plan`（update 不新建，KeyError）；web 新增「Flow Library 管理」tab：模板元字段展示 + steps YAML 编辑保存（`_apply_template_edit` 从原模板回填元字段，编辑表单不接触）+ 模板/Plan 删除二次确认（session_state 状态机）。顺手修 test_llm fixture 隔离 bug（`_LOCAL_CONFIG_PATH` 未 patch，真实 local.yaml 污染测试 key，即基线 2 failed 根因）（feat/f002-g16-flow-ui，TDD 红绿 17 新用例，277 passed 全绿，关羽跨家族 review 放行覆盖 SHA ab456d4）
- [x] **G17 图表质量修复**: 铲屎官三件事（①图表维度少 ②空图表/错误图表 ③Plan 执行过程可见+默认折叠）。根因修复：visualizer `y=list` 逐列展开多 trace（旧代码 `df[list]`→2D 嵌套喂 plotly→空图/畸形图，A 轨冷启动模板全中招；多指标只画 1 错 trace=维度少）+ web「🔍 执行过程」默认折叠 expander（`_format_run_log` 步骤表：✅/❌+op+图表产出+失败原因）+ fake 污染产物清理（`tpl-fake-da4d81cc` 晋升进包内置库劫持 B 轨=错误图表源头；证据归档 quarantine commit 进分支）+ promoter 断根护栏测试（源 plan 删则不复活晋升，真实库实测 scan==[]）（feat/f002-g17-chart-quality，TDD 红绿 9 新用例，286 passed 无回归，关羽跨家族 review 放行，merge commit de47fc1）
- [x] **G18 执行过程增强 + 流式 Reviewer + llm_calls 修正**: 铲屎官「①命中模板执行过程输出太少 ②AI reviewer 思考过程流式展示别死等」+ review 中追问「reviewer 也消耗 token 要计入」。①executor entry 加 `args`/`shape_before/after` + model 步 report 扩 title/x/y，web 渲染（旧格式兼容）②流式三层：`chat_stream`（base 回落）/ `review_stream(on_delta)`（base 回落）/ `run(on_review_delta=)`，OpenAI stream=True，web `st.empty()` 节流增量刷新 ③reviewer 被调 `llm_calls += 1`（修 A 轨+reviewer 漏计，test_cold_start 两处期望连动修正——原 0 本就是漏计）（feat/f002-g18，TDD 红绿 20 新用例，306 passed 无回归，关羽跨家族 review 放行覆盖 SHA 830c1a7，merge commit 6756c65）
- [ ] **G18 连调验证（hot，合入后待办）**: 真实 LLM 连调验证流式体感——节流阈值 8 的最终裁判；短报告（<8 chunk）流式失效边缘一并观察（占位区不刷新、结束时清空）
- [ ] **llm_calls 语义口径（关羽 G18 review 记录 1，P7+）**: 现语义="调用次数"非"token 数"——`FakeReviewer` 被调也 +1，默认 web LLM 加载失败退 Fake 时 dashboard `total_llm_calls` 虚高。真实 token 统计需 provider 透出 usage 字段（流式在末 chunk 需聚合），与 `is_real` 判定一起做
- [ ] **G17 防再生（hot，关羽 review 归因修正）**: Fake 测试污染包内置库的**主根因是测试用默认 `FlowLibrary()`**（test_cold_start.py 等 + Fake generator → 产物直接落盘包目录）。修法：测试统一 tmp store fixture（对齐 test_promoter 惯例），CLI 无 `--lib` 默认库选址可议（改用户目录属 CLI 设计变更需铲屎官确认）。不修这条，同类污染还会发生
- [ ] **OQ 晋升门槛收紧（待铲屎官拍板，spec §7.3 语义变更）**: 现"≥3 全成功但 0 次人工采纳"即可晋升。候选：要求 ≥1 次 `user_adopted=True`。注意归因：门槛只是**放大器**，测试污染才是主根因（云长 review 第 6 点），收紧是防御加固非根治
- [ ] **外部 AI P5**: B 轨匹配依赖 intent 分类（未分类 intent=None 时跳过 B 轨）。符合当前规则分类器设计，**不改，记入候选**——P7+ 可考虑未分类问题的模糊匹配（embedding 相似度）
- [ ] **AC-1 Postgres**: 补 `PostgresAdapter`（接生产 DB 时实现，MVP 未需要）
- [ ] **minor-1（关羽 G16 review 记档）**: `_parse_steps_yaml` 只校验 `op` 存在，不校验 `args` 是 dict——用户写 `args: [a,b]` 会到 executor 才炸，建议加 `isinstance(item.get("args"), dict)` 前置校验（低危，高级用户可回滚）
- [ ] **minor-2（关羽 G16 review 记档）**: `update_plan` 在 web 层无调用者（Plan 轨只查看+删除，store 层方法保留为 API 对称性 + 测试兜底）；另：删模板后源模板 missing 的 Plan 晋升路径需 promoter 容忍"源模板不存在"（晋升机制 OWN 边界）
- [ ] **OQ-1 op_spec 漂移**: 12 op 手写维护 + 抽样测试够；P7+ 上 pydantic/introspect 自动同步 op 函数签名
- [ ] **OQ-2 晋升 N 值调优**: N=3 硬编码 MVP 跑起来观察首批晋升 plan 质量后再调
- [ ] **OQ-3 空 content 日志**: GLM-5.2 reasoning_tokens 吃光 content 为空时，加日志记录便于排查（当前靠 _parse_json ValueError 触发重试，逻辑对但缺日志）
