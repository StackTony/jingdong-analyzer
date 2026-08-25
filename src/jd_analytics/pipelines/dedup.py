"""
去重 Pipeline（spec §4.4 - SPU 级去重）

URL hash + SPU ID 双重去重。
同 SPU 多 SKU 取评价数最大 SKU 作代表（Q4 拍板）。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class DedupPipeline:
    """SPU 级去重 + 代表 SKU 选举"""

    def __init__(self):
        self.seen_spu: set[str] = set()
        self.spu_max_review: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        spu_id = item.get("spu_id")
        if not spu_id:
            return item

        # SPU 已见过 → 比较评价数，保留最大（Q4）
        if spu_id in self.spu_max_review:
            current_max = self.spu_max_review[spu_id]
            if (item.get("cumu_review_count", 0) or 0) > (
                current_max.get("cumu_review_count", 0) or 0
            ):
                # 新记录更大 → 用新的替换
                self.spu_max_review[spu_id] = item
                logger.debug(f"SPU {spu_id}: new representative SKU (higher review count)")
            # 返回 None 表示丢弃（这条不进后续 pipeline）
            from scrapy.exceptions import DropItem
            raise DropItem(f"Duplicate SPU {spu_id}, keeping max review count")
        else:
            self.spu_max_review[spu_id] = item

        return item
