"""
入库 Pipeline（spec §4.1）

结构化字段入主库。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from jd_analytics.models import SpuMaster, SkuDetail, MonthlyDelta, Batch
from jd_analytics.settings import DATABASE_URL

logger = logging.getLogger(__name__)


class StoragePipeline:
    """结构化字段入库"""

    def __init__(self):
        self.engine = create_engine(DATABASE_URL)
        self._load_brand_normalization()

    def _load_brand_normalization(self):
        from pathlib import Path
        path = Path(__file__).parent.parent / "config" / "brand_normalization.yaml"
        with open(path, encoding="utf-8") as f:
            self.brand_config = yaml.safe_load(f)

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        spu_id = item["spu_id"]
        brand_raw = item.get("brand_name_raw")
        brand_normalized = self._normalize_brand(brand_raw)
        cumu_review = item.get("cumu_review_count") or 0
        price = item.get("price") or 0.0

        with self.engine.begin() as conn:
            # 1. upsert spu_master
            self._upsert_spu(conn, spu_id, brand_raw, brand_normalized, item)
            # 2. upsert sku_detail
            self._upsert_sku(conn, spu_id, cumu_review, price)
            # 3. insert monthly_delta
            self._insert_monthly_delta(conn, spu_id, cumu_review, price, item)

        return item

    def _upsert_spu(self, conn, spu_id: str, brand_raw: str | None,
                    brand_normalized: str | None, item: dict[str, Any]):
        existing = conn.execute(
            select(SpuMaster).where(SpuMaster.spu_id == spu_id)
        ).first()

        if existing:
            conn.execute(
                SpuMaster.__table__.update()
                .where(SpuMaster.spu_id == spu_id)
                .values(
                    brand_name_raw=brand_raw or existing.brand_name_raw,
                    brand_name_normalized=brand_normalized or existing.brand_name_normalized,
                    title=item.get("title") or existing.title,
                    last_seen_batch=item.get("batch_id") or existing.last_seen_batch,
                    is_active=True,
                )
            )
        else:
            conn.execute(
                SpuMaster.__table__.insert().values(
                    spu_id=spu_id,
                    brand_id=brand_normalized or spu_id,  # 兜底用 spu_id
                    brand_name_raw=brand_raw,
                    brand_name_normalized=brand_normalized,
                    cid="",  # 由 categories.yaml 反查填充
                    category=item.get("category", ""),
                    title=item.get("title"),
                    first_seen_batch=item.get("batch_id"),
                    last_seen_batch=item.get("batch_id"),
                    is_active=True,
                )
            )

    def _upsert_sku(self, conn, spu_id: str, cumu_review: int, price: float):
        # demo：简化为 SPU = SKU（实际有 SPU/SKU 分离）
        sku_id = spu_id
        existing = conn.execute(
            select(SkuDetail).where(SkuDetail.sku_id == sku_id)
        ).first()

        now = datetime.now(timezone.utc).isoformat()
        if existing:
            conn.execute(
                SkuDetail.__table__.update()
                .where(SkuDetail.sku_id == sku_id)
                .values(
                    cumu_review_count=cumu_review,
                    price=price,
                    review_count_updated_at=now,
                )
            )
        else:
            conn.execute(
                SkuDetail.__table__.insert().values(
                    sku_id=sku_id,
                    spu_id=spu_id,
                    price=price,
                    cumu_review_count=cumu_review,
                    review_count_updated_at=now,
                    is_representative=True,
                )
            )

    def _insert_monthly_delta(self, conn, spu_id: str, cumu_review: int,
                              price: float, item: dict[str, Any]):
        batch_id = item["batch_id"]
        month = item.get("month") or datetime.now(timezone.utc).strftime("%Y-%m")

        # 取上月累计评价数
        prev = conn.execute(
            select(MonthlyDelta.cumu_review_count)
            .where(MonthlyDelta.spu_id == spu_id)
            .order_by(MonthlyDelta.month.desc())
            .limit(1)
        ).first()
        prev_count = prev[0] if prev else None

        delta = (cumu_review - prev_count) if prev_count is not None else None
        negative = (delta is not None and delta < 0)
        sales_value = (delta * price) if delta and delta > 0 else 0.0

        # SQLite UPSERT (INSERT OR REPLACE)
        conn.execute(
            MonthlyDelta.__table__.insert().values(
                batch_id=batch_id,
                month=month,
                spu_id=spu_id,
                cumu_review_count=cumu_review,
                prev_review_count=prev_count,
                delta=delta,
                negative_delta=negative,
                price_sampled=price,
                sales_value_proxy=sales_value,
            ).prefix_with("OR REPLACE")
        )

    def _normalize_brand(self, raw: str | None) -> str | None:
        """应用 brand_normalization.yaml 规则（spec §6.2）"""
        if not raw:
            return None

        result = raw
        rules = self.brand_config.get("normalization_rules", [])
        for rule in rules:
            if rule.get("field") != "brand_name_raw":
                continue
            transforms = rule.get("transforms", [])

            for t in transforms:
                if "remove_parentheses" in t and t["remove_parentheses"]:
                    import re
                    result = re.sub(r"[\(\)\(\)（）（]", "", result)
                if "remove_suffix" in t:
                    for suffix in t["remove_suffix"]:
                        if result.endswith(suffix):
                            result = result[:-len(suffix)]
                if "alias_mapping" in t:
                    for alias, std in t["alias_mapping"].items():
                        if result == alias:
                            result = std
                            break

        return result.strip() if result else None
