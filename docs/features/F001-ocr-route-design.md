---
feature_ids: [F001]
related_features: [F001]
topics: [ocr, paddleocr, screenshot, anti-bot, design]
doc_kind: design
created: 2026-08-26
---

# F001 OCR 路线设计增补（方案 A 全 OCR）

> Status: design | Owner: 文若（@cat-rp3g6qqr）

## 背景

铲屎官拍板：在现有 DrissionPage 反爬栈基础上新增"全 OCR 路线"作为数据提取备选。
- 反爬栈五层防御**全保留**（登录/限速/代理/指纹/行为模拟）
- 数据提取层从"监听 JSON 接口"换成"整页截图 + PaddleOCR-VL 提取"
- 截图保留 7 天后自动删除
- **本期不实际爬取测试**，代码实现完 → @云长 review 反爬是否到位

## 范围

### 本期做
- 新增 `spiders/ocr_spider.py`：复用 DrissionSpider 登录+反爬逻辑，重写数据提取层
- 新增 `pipelines/ocr_extract.py`：PaddleOCR-VL 提取 pipeline
- 新增 `utils/screenshot_gc.py`：7 天自动清理截图
- 新增 OCR 配置文件 2 个
- 修改 `settings.py` / `cli.py` / `pyproject.toml` / `.gitignore`
- 单元测试（mock 截图，不实际爬取）

### 本期不做
- 实际爬取测试（等关羽 review 后决定）
- OCR 引擎切换为云 API（保留配置接口，本期固定 PaddleOCR-VL 自部署）
- 部署形态

## 架构

### 数据流

```
登录态（复用 DrissionSpider）
    ↓
访问搜索页（复用）
    ↓
滚动加载（复用）
    ↓
整页截图 → 保存 PNG（7天GC）
    ↓
PaddleOCR-VL 提取文字
    ↓
按区域规则结构化（商品卡片 → 逐卡片解析字段）
    ↓
ValidationPipeline → DedupPipeline → StoragePipeline
（pipeline 链完全复用，item 字段对齐 drission_spider）
```

### 关键设计决策

1. **OCR 引擎**：PaddleOCR-VL 1.5（0.9B 参数，自部署）
   - 免费、本地推理、复杂版式能力强
   - 支持 109 种语言，中文识别 SOTA
   - CPU 可跑（慢），GPU 更快
   - 配置接口保留切换云 API 的能力

2. **截图粒度**：整页截图 + 区域裁剪
   - 整页 1 张约 1MB
   - 每页约 60 商品 → 11 万商品 ≈ 1800 张整页 ≈ 1.8 GB/月
   - 比逐卡片截图省 60 倍存储

3. **OCR 结果字段对齐 drission_spider 的 item schema**
   - 下游 pipeline 不用改
   - aggregator 不用改
   - 双榜算法不变

4. **截图保留 7 天**
   - `data/screenshots/<batch_id>/<category>/page_<p>_<ts>.png`
   - `screenshot_gc.py` 扫描 mtime > 7d 的文件删除
   - 用于合规审计 + OCR 复跑

5. **反爬栈保留**
   - 登录、UA 轮换、限速、代理池接口、行为模拟**全复用**
   - 不因 OCR 路线简化任何反爬层

## 文件清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `spiders/ocr_spider.py` | 新增 | OCR 路线主 spider |
| `pipelines/ocr_extract.py` | 新增 | PaddleOCR-VL 提取 pipeline |
| `utils/screenshot_gc.py` | 新增 | 7 天清理任务 |
| `config/ocr_config.yaml` | 新增 | OCR 引擎配置 |
| `config/selectors/ocr_regions_v1.yaml` | 新增 | 截图区域定位规则 |
| `settings.py` | 修改 | 加 SCREENSHOT_PATH / RETENTION / OCR_ENGINE |
| `cli.py` | 修改 | 加 `--mode ocr` 切换 |
| `pyproject.toml` | 修改 | 加 paddleocr / paddlepaddle 依赖 |
| `.gitignore` | 修改 | 加 `data/screenshots/` 排除 |
| `tests/test_ocr_extract.py` | 新增 | mock 截图单元测试 |

## 验收标准

- [ ] AC-1: `ocr_spider.py` 能复用 DrissionSpider 登录态
- [ ] AC-2: 截图保存到 `data/screenshots/<batch_id>/<category>/`
- [ ] AC-3: `ocr_extract.py` 能从 mock 截图提取结构化字段
- [ ] AC-4: `screenshot_gc.py` 能删除 7 天前的截图
- [ ] AC-5: `cli.py --mode ocr` 能切换到 OCR 路线
- [ ] AC-6: 反爬栈五层中间件全部保留
- [ ] AC-7: 单元测试 mock 截图通过
- [ ] AC-8: 不实际访问京东（试爬等关羽 review 后决定）

## 风险

| 风险 | 等级 | 应对 |
|---|---|---|
| PaddleOCR-VL 安装复杂（paddlepaddle 依赖） | 中 | 配置可选依赖，import 失败时降级 |
| OCR 误识率 1-5% | 中 | 配置信度阈值 + 字段校验 |
| 截图存储失控 | 低 | 7 天 GC + .gitignore |
| 京东页面改版导致区域定位失效 | 中 | 选择器版本化 + 月度冒烟 |

## Open Questions

1. OCR 引擎最终选 PaddleOCR-VL 还是 qwen3.5-ocr API？（本期固定 PaddleOCR-VL，后续可换）
2. 截图区域定位用 CSS selector 还是坐标比例？（本期用 CSS selector，更鲁棒）
3. OCR 失败时是否回退到 JSON 接口？（本期不回退，纯 OCR 路线）

## Phase 路线

- **Phase 0（本期）**：代码实现 + 单元测试，不实际爬取
- **Phase 1**：关羽 review 反爬栈 → 修复 → 试爬 1 品类验证
- **Phase 2**：11 品类 cid2/cid3 确认 + 正式月度采集
- **Phase 3+**：评估是否切云 API / 加 GPU 加速
