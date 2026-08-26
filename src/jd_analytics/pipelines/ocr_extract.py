"""
OCR 提取 Pipeline（spec F001-ocr-route §3.3）

用 PaddleOCR-VL 从京东搜索页截图提取结构化商品信息。

核心流程：
1. 加载截图
2. PaddleOCR-VL 识别整页文字（带 bounding box）
3. 按 ocr_regions_v1.yaml 的 CSS selector 规则定位字段区域
4. 后处理（去 HTML 标签、解析价格/销量）
5. 返回 list[item_dict]，字段对齐 drission_spider._build_item

注意：
- paddleocr 是可选依赖（避免硬依赖），import 失败时用 MockOcrExtractor
- 本期不实际跑 OCR，单元测试用 MockOcrExtractor
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class PaddleOCRVLExtractor:
    """PaddleOCR-VL 提取器

    使用 PaddleOCR 3.x 的 PaddleOCR-VL 模型（0.9B 参数 VLM）
    支持复杂版式、表格、109 种语言

    安装：pip install paddleocr paddlepaddle
    """

    def __init__(self, ocr_config: dict[str, Any]):
        self.config = ocr_config
        self._ocr_engine = None
        self._regions_config = None

        # 加载区域定位规则
        regions_path = (
            Path(__file__).parent.parent
            / "config"
            / "selectors"
            / "ocr_regions_v1.yaml"
        )
        try:
            with open(regions_path, encoding="utf-8") as f:
                self._regions_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load ocr_regions: {e}")

    def _get_engine(self):
        """lazy 加载 PaddleOCR 引擎"""
        if self._ocr_engine is not None:
            return self._ocr_engine

        try:
            from paddleocr import PaddleOCR

            vl_config = self.config.get("paddleocr_vl", {})
            model = vl_config.get("model", "PaddleOCR-VL")
            lang = vl_config.get("lang", "ch")

            # PaddleOCR-VL 用 PaddleOCR 类初始化
            # 注：实际 API 以 paddleocr 3.x 文档为准
            self._ocr_engine = PaddleOCR(
                model=model,
                lang=lang,
                device=vl_config.get("device", "cpu"),
            )
            logger.info(f"PaddleOCR engine loaded: model={model} lang={lang}")
        except Exception as e:
            logger.error(f"Failed to init PaddleOCR: {e}")
            raise

        return self._ocr_engine

    def extract_from_screenshot(
        self,
        screenshot_path: Path,
        category_name: str,
        keyword: str,
        page: int,
        batch_id: str,
        month: str,
    ) -> list[dict[str, Any]]:
        """从截图提取结构化商品列表

        返回 list[item_dict]，字段对齐 drission_spider._build_item
        """
        if not screenshot_path or not Path(screenshot_path).exists():
            logger.warning(f"Screenshot not found: {screenshot_path}")
            return []

        # 1. 跑 OCR
        engine = self._get_engine()
        try:
            ocr_result = engine.ocr(str(screenshot_path), cls=True)
        except Exception as e:
            logger.error(f"OCR failed for {screenshot_path}: {e}")
            return []

        if not ocr_result:
            logger.warning(f"OCR returned empty for {screenshot_path}")
            return []

        # 2. OCR 结果是 [[box, (text, confidence)], ...]
        # 把 text + box 提取出来
        texts_with_boxes = self._parse_ocr_result(ocr_result)

        # 3. 按区域规则结构化
        # 简化版：按文字内容匹配字段（不依赖坐标，靠正则 + 关键词）
        # 完整版应该用 box 坐标聚类到商品卡片（需要页面 DOM 配合）
        items = self._structure_items(
            texts_with_boxes, category_name, keyword, page, batch_id, month
        )

        return items

    def _parse_ocr_result(
        self, ocr_result: Any
    ) -> list[dict[str, Any]]:
        """解析 PaddleOCR 原始结果为 [{text, confidence, box}, ...]"""
        texts: list[dict[str, Any]] = []

        # PaddleOCR 返回格式：[page_result] 其中 page_result = [[box, (text, conf)], ...]
        if not ocr_result:
            return texts

        page_data = ocr_result[0] if isinstance(ocr_result, list) else ocr_result

        if not page_data:
            return texts

        for entry in page_data:
            try:
                if isinstance(entry, list) and len(entry) >= 2:
                    box = entry[0]
                    text_conf = entry[1]
                    if isinstance(text_conf, list) and len(text_conf) >= 2:
                        text = text_conf[0]
                        conf = text_conf[1]
                    elif isinstance(text_conf, tuple) and len(text_conf) >= 2:
                        text = text_conf[0]
                        conf = text_conf[1]
                    else:
                        continue

                    texts.append({
                        "text": str(text),
                        "confidence": float(conf),
                        "box": box,
                    })
            except Exception as e:
                logger.debug(f"Failed to parse OCR entry: {e}")
                continue

        return texts

    def _structure_items(
        self,
        texts_with_boxes: list[dict[str, Any]],
        category_name: str,
        keyword: str,
        page: int,
        batch_id: str,
        month: str,
    ) -> list[dict[str, Any]]:
        """把 OCR 文字结果结构化为商品 item 列表

        P1-4 修复（云长 review）：用 box 坐标聚类替代索引配对

        策略：
        1. 按 box 中心 y 蝶标聚类成行（同 y 附近归一行）
        2. 行内按 x 坐标聚类成商品卡片
        3. 每个卡片内：识别价格/SKU/标题/店铺/销量，全部归一个商品

        京东搜索页布局：网格，每行 5 卡片，每卡 ~250x500px
        """
        items: list[dict[str, Any]] = []

        confidence_threshold = (
            self.config.get("paddleocr_vl", {}).get("confidence_threshold", 0.80)
        )
        clustering_cfg = self.config.get("clustering", {})
        row_y_threshold = clustering_cfg.get("row_y_threshold", 60)
        card_x_threshold = clustering_cfg.get("card_x_threshold", 280)
        card_min_texts = clustering_cfg.get("card_min_texts", 2)
        max_items_per_page = clustering_cfg.get("max_items_per_page", 60)

        # 1. 过滤低置信度 + 计算 box 中心点
        valid_entries: list[dict[str, Any]] = []
        for entry in texts_with_boxes:
            text = entry.get("text", "").strip()
            conf = entry.get("confidence", 0)
            box = entry.get("box")

            if not text or conf < confidence_threshold:
                continue
            if not box or len(box) < 2:
                continue

            # box 格式：[[x1,y1], [x2,y2], [x3,y3], [x4,y4]] 或 [[x,y],[w,h]]
            try:
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
            except (IndexError, TypeError):
                continue

            valid_entries.append({
                "text": text,
                "confidence": conf,
                "box": box,
                "cx": cx,
                "cy": cy,
            })

        if not valid_entries:
            logger.warning(f"No valid OCR entries after filtering")
            return items

        # 2. 按 y 中心聚类成行
        # 先按 y 排序，然后相邻 y 距离 < threshold 归为一行
        sorted_by_y = sorted(valid_entries, key=lambda e: e["cy"])
        rows: list[list[dict[str, Any]]] = []
        current_row: list[dict[str, Any]] = [sorted_by_y[0]]
        current_y = sorted_by_y[0]["cy"]

        for entry in sorted_by_y[1:]:
            if abs(entry["cy"] - current_y) < row_y_threshold:
                current_row.append(entry)
                # 更新当前行的 y 均值（更稳定）
                current_y = sum(e["cy"] for e in current_row) / len(current_row)
            else:
                rows.append(current_row)
                current_row = [entry]
                current_y = entry["cy"]
        if current_row:
            rows.append(current_row)

        # 3. 每行内按 x 聚类成卡片
        for row_idx, row in enumerate(rows):
            row_sorted = sorted(row, key=lambda e: e["cx"])
            cards: list[list[dict[str, Any]]] = []
            current_card: list[dict[str, Any]] = [row_sorted[0]]
            current_x = row_sorted[0]["cx"]

            for entry in row_sorted[1:]:
                if abs(entry["cx"] - current_x) < card_x_threshold:
                    current_card.append(entry)
                    current_x = sum(e["cx"] for e in current_card) / len(current_card)
                else:
                    cards.append(current_card)
                    current_card = [entry]
                    current_x = entry["cx"]
            if current_card:
                cards.append(current_card)

            # 4. 每个卡片内提取字段
            for card_idx, card_entries in enumerate(cards):
                if len(card_entries) < card_min_texts:
                    continue

                item = self._build_item_from_card(
                    card_entries, category_name, keyword,
                    page, batch_id, month, confidence_threshold,
                )
                if item:
                    items.append(item)

                if len(items) >= max_items_per_page:
                    logger.info(
                        f"Reached max_items_per_page ({max_items_per_page}), "
                        f"stopping"
                    )
                    return items

        logger.info(
            f"OCR clustered {len(items)} items from {len(valid_entries)} text blocks "
            f"across {len(rows)} rows"
        )
        return items

    def _build_item_from_card(
        self,
        card_entries: list[dict[str, Any]],
        category_name: str,
        keyword: str,
        page: int,
        batch_id: str,
        month: str,
        confidence_threshold: float,
    ) -> dict[str, Any] | None:
        """从单个卡片的文本块提取商品字段

        每个卡片是一个商品，所有文本块按字段类型分类：
        - 价格：含 ¥ 前缀的数字
        - SKU ID：10-13 位纯数字 或 item.jd.com/XXX
        - 销量：N万+ / N+ / 已有N人评价
        - 店铺名：含 旗舰店/京东自营/专卖店 关键词
        - 标题：剩余的较长文本
        """
        price: float | None = None
        sku_id: str | None = None
        title: str = ""
        shop: str = ""
        sale = 0
        low_conf = False

        # 卡片内按 y 从上到下、x 从左到右排序（标题通常在最上面）
        card_sorted = sorted(card_entries, key=lambda e: (e["cy"], e["cx"]))

        for entry in card_sorted:
            text = entry["text"]
            conf = entry["confidence"]

            if conf < confidence_threshold:
                low_conf = True

            # 价格（¥ 前缀，只取第一个匹配的）
            if price is None:
                price_match = re.search(r"¥\s*(\d+(?:\.\d{1,2})?)", text)
                if price_match:
                    try:
                        price = float(price_match.group(1))
                        continue
                    except ValueError:
                        pass

            # SKU ID（10-13 位数字 或 item.jd.com/XXX）
            if sku_id is None:
                sku_match = re.search(r"(?:item\.jd\.com/)?(\d{10,13})", text)
                if sku_match:
                    sku_id = sku_match.group(1)
                    continue

            # 销量
            if sale == 0:
                sale = self._parse_sales_from_text(text)
                if sale > 0:
                    continue

            # 店铺名
            if not shop and any(
                kw in text for kw in ["旗舰店", "京东自营", "专卖店", "专营店"]
            ):
                shop = text.strip()
                continue

            # 标题：较长且不含特殊字段标识
            if (
                len(text) > 10
                and "¥" not in text
                and not re.match(r"^\d{10,13}$", text)
                and not any(kw in text for kw in ["旗舰店", "京东自营"])
                and "已有" not in text
                and "评价" not in text
            ):
                if len(text) > len(title):
                    title = text.strip()

        # 至少要有价格或 SKU 才算有效商品
        if price is None and sku_id is None:
            return None

        # 没找到 SKU 用占位符
        if sku_id is None:
            sku_id = f"ocr_unknown_{page}_{category_name}_{hash(title) % 100000}"

        item = {
            "spu_id": sku_id,
            "batch_id": batch_id,
            "month": month,
            "category": category_name,
            "keyword": keyword,
            "title": title,
            "brand_name_raw": shop,
            "url": (
                f"https://item.jd.com/{sku_id}.html"
                if not sku_id.startswith("ocr_unknown")
                else ""
            ),
            "page": page,
            "price": price,
            "ori_price": None,
            "cumu_review_count": sale,
            "total_sales": sale,
            "total_sales_raw": "",
            "good_count": 0,
            "general_count": 0,
            "poor_count": 0,
            "show_count": 0,
            "low_confidence": low_conf,
        }
        return item

    def _parse_sales_from_text(self, text: str) -> int:
        """从文字解析销量（'100万+' / '5000+' / '已有 300000 人评价'）"""
        # '100万+'
        m = re.search(r"(\d+(?:\.\d+)?)\s*万\+?", text)
        if m:
            return int(float(m.group(1)) * 10000)

        # '5000+'
        m = re.search(r"(\d+)\+", text)
        if m:
            return int(m.group(1))

        # '已有 300000 人评价'
        m = re.search(r"已有\s*([\d,]+)\s*人评价", text)
        if m:
            return int(m.group(1).replace(",", ""))

        return 0


class MockOcrExtractor:
    """Mock OCR 提取器（用于 dry-run 和单元测试）

    不实际跑 OCR，返回预设的 mock 数据
    """

    def __init__(self, ocr_config: dict[str, Any]):
        self.config = ocr_config

    def extract_from_screenshot(
        self,
        screenshot_path: Path,
        category_name: str,
        keyword: str,
        page: int,
        batch_id: str,
        month: str,
    ) -> list[dict[str, Any]]:
        """返回 mock 商品列表（3 个示例商品）"""
        logger.info(
            f"[MOCK OCR] Extracting from {screenshot_path} "
            f"(category={category_name}, page={page})"
        )

        mock_items = [
            {
                "spu_id": f"mock_sku_{page}_1",
                "batch_id": batch_id,
                "month": month,
                "category": category_name,
                "keyword": keyword,
                "title": f"[Mock] 商品示例 {page}-1",
                "brand_name_raw": "示例旗舰店",
                "url": "https://item.jd.com/mock_sku_1.html",
                "page": page,
                "price": 99.9,
                "ori_price": 129.9,
                "cumu_review_count": 5000,
                "total_sales": 5000,
                "total_sales_raw": "5000+",
                "good_count": 0,
                "general_count": 0,
                "poor_count": 0,
                "show_count": 0,
                "low_confidence": False,
            },
            {
                "spu_id": f"mock_sku_{page}_2",
                "batch_id": batch_id,
                "month": month,
                "category": category_name,
                "keyword": keyword,
                "title": f"[Mock] 商品示例 {page}-2",
                "brand_name_raw": "示例京东自营",
                "url": "https://item.jd.com/mock_sku_2.html",
                "page": page,
                "price": 199.0,
                "ori_price": 249.0,
                "cumu_review_count": 1000000,
                "total_sales": 1000000,
                "total_sales_raw": "100万+",
                "good_count": 0,
                "general_count": 0,
                "poor_count": 0,
                "show_count": 0,
                "low_confidence": False,
            },
        ]
        return mock_items
