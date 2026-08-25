"""
数据校验 Pipeline（spec §7.1 极简版）

不用 pandera，直接 dict 校验。
"""
from __future__ import annotations

import logging
from typing import Any

from scrapy.exceptions import DropItem

logger = logging.getLogger(__name__)


# 必填字段
REQUIRED_FIELDS = ["spu_id", "batch_id", "category", "url"]
# 数值字段必须 >= 0
NUMERIC_NON_NEG = ["cumu_review_count", "good_count", "general_count", "poor_count", "show_count", "price"]


class ValidationPipeline:
    """轻量数据校验"""

    def __init__(self):
        self.rejected_count = 0

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        # 必填字段
        for field in REQUIRED_FIELDS:
            if not item.get(field):
                self.rejected_count += 1
                raise DropItem(f"Missing required field {field}")

        # 数值非负
        for field in NUMERIC_NON_NEG:
            val = item.get(field)
            if val is not None and val < 0:
                self.rejected_count += 1
                raise DropItem(f"Negative value for {field}: {val}")

        return item
