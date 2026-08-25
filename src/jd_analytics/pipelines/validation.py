"""
数据校验 Pipeline（spec §7.1）

pandera schema 校验每条记录。
"""
from __future__ import annotations

import logging
from typing import Any

import pandera as pa
from pandera import Column, DataFrameSchema, Check

logger = logging.getLogger(__name__)


# 单条 schema（spec §7.1）
item_schema = DataFrameSchema({
    "spu_id": Column(str, nullable=False),
    "batch_id": Column(str, nullable=False),
    "title": Column(str, nullable=True),
    "brand_name_raw": Column(str, nullable=True),
    "cumu_review_count": Column(int, nullable=True, checks=Check.ge(0)),
    "price": Column(float, nullable=True, checks=Check.ge(0)),
    "url": Column(str, nullable=False),
    "fetched_at": Column(float, nullable=True),
})


class ValidationPipeline:
    """pandera 单条校验"""

    def __init__(self):
        self.rejected_count = 0

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        try:
            # 单条 → 单行 DataFrame 校验
            import pandas as pd
            df = pd.DataFrame([item])
            item_schema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as e:
            self.rejected_count += 1
            logger.warning(
                f"Validation failed for {item.get('spu_id', 'unknown')}: "
                f"{e.failure_cases.head()}"
            )
            # 失败记录进 retry_queue（spec §8.3）
            from jd_analytics.pipelines.retry import enqueue_retry
            enqueue_retry(item["url"], item.get("batch_id"), "validation_failed")
            raise DropItem(f"Validation failed for {item.get('spu_id')}")

        return item


from scrapy.exceptions import DropItem  # noqa: E402
