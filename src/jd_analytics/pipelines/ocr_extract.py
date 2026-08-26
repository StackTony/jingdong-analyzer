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

        简化版策略：用正则识别商品卡片
        - 价格模式：¥XXXX.XX 或 XXXX.XX
        - SKU ID 模式：item.jd.com/XXXXX 或纯数字 10-13 位
        - 销量模式：N万+ / N+ / 已有N人评价

        完整版应该按 box 坐标聚类（本期不做，等试爬验证后补）
        """
        items: list[dict[str, Any]] = []

        # 收集所有文字
        all_texts = [t["text"] for t in texts_with_boxes]

        # 用正则提取关键字段
        prices = []
        sku_ids = []
        titles = []
        shop_names = []
        sales = []

        confidence_threshold = (
            self.config.get("paddleocr_vl", {}).get("confidence_threshold", 0.80)
        )

        for entry in texts_with_boxes:
            text = entry["text"]
            conf = entry["confidence"]

            if conf < confidence_threshold:
                logger.debug(f"Low confidence text skipped: {text} ({conf})")
                continue

            # 价格
            price_match = re.search(r"¥?(\d+(?:\.\d{1,2})?)", text)
            if price_match and "¥" in text:
                try:
                    prices.append(float(price_match.group(1)))
                except ValueError:
                    pass

            # SKU ID（item.jd.com/123456 或纯 10-13 位数字）
            sku_match = re.search(r"(?:item\.jd\.com/)?(\d{10,13})", text)
            if sku_match:
                sku_ids.append(sku_match.group(1))

            # 销量
            sales_match = self._parse_sales_from_text(text)
            if sales_match:
                sales.append(sales_match)

            # 店铺名（含"旗舰店" / "京东自营"等关键词）
            if any(kw in text for kw in ["旗舰店", "京东自营", "专卖店", "专营店"]):
                shop_names.append(text.strip())

            # 标题（含商品特征词，较长且非价格/SKU）
            if (
                len(text) > 10
                and "¥" not in text
                and not re.match(r"^\d{10,13}$", text)
                and not any(kw in text for kw in ["旗舰店", "京东自营"])
                and "已有" not in text
                and "评价" not in text
            ):
                titles.append(text.strip())

        # 按"每页约 60 商品"对齐（简化版，不精确配对）
        # 完整版需要 box 坐标聚类（本期不做）
        max_items = max(len(prices), len(sku_ids), 1)

        for i in range(min(max_items, 60)):  # 京东每页约 60 商品
            price = prices[i] if i < len(prices) else None
            sku_id = sku_ids[i] if i < len(sku_ids) else f"ocr_unknown_{page}_{i}"
            title = titles[i] if i < len(titles) else ""
            shop = shop_names[i] if i < len(shop_names) else ""
            sale = sales[i] if i < len(sales) else 0

            # 至少要有价格或 SKU 才算有效商品
            if not price and sku_id.startswith("ocr_unknown"):
                continue

            item = {
                "spu_id": sku_id,
                "batch_id": batch_id,
                "month": month,
                "category": category_name,
                "keyword": keyword,
                "title": title,
                "brand_name_raw": shop,  # 京东店铺名通常含品牌信息
                "url": f"https://item.jd.com/{sku_id}.html" if not sku_id.startswith("ocr_unknown") else "",
                "page": page,
                "price": price,
                "ori_price": None,
                "cumu_review_count": sale,  # 字段名沿用，语义=销量
                "total_sales": sale,
                "total_sales_raw": "",
                "good_count": 0,
                "general_count": 0,
                "poor_count": 0,
                "show_count": 0,
                "low_confidence": any(
                    t["confidence"] < confidence_threshold
                    for t in texts_with_boxes
                    if t["text"] in [title, shop, str(price)]
                ),
            }
            items.append(item)

        logger.info(
            f"OCR structured {len(items)} items from {len(texts_with_boxes)} text blocks"
        )
        return items

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
