"""
入库 Pipeline（spec §4.1 极简版）

结构化字段入主库 SQLite。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from jd_analytics.models import SpuMaster, SkuDetail, MonthlyDelta
from jd_analytics.settings import DATABASE_URL

logger = logging.getLogger(__name__)


class StoragePipeline:
    """结构化字段入库 + 品牌标准化"""

    def __init__(self):
        self.engine = create_engine(DATABASE_URL)
        self._load_brand_normalization()

    def _load_brand_normalization(self):
        from pathlib import Path
        path = Path(__file__).parent.parent / "config" / "brand_normalization.yaml"
        try:
            with open(path, encoding="utf-8") as f:
                self.brand_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load brand config: {e}")
            self.brand_config = {}

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        spu_id = item["spu_id"]
        brand_raw = item.get("brand_name_raw")
        brand_normalized = self._normalize_brand(brand_raw)
        cumu_review = item.get("cumu_review_count") or 0
        price = item.get("price") or 0.0

        try:
            with self.engine.begin() as conn:
                self._upsert_spu(conn, spu_id, brand_raw, brand_normalized, item)
                self._upsert_sku(conn, spu_id, cumu_review, price)
                self._upsert_monthly_delta(conn, spu_id, cumu_review, price, item)
        except Exception as e:
            logger.error(f"Storage failed for spu={spu_id}: {e}")
            raise

        return item

    def _upsert_spu(self, conn, spu_id: str, brand_raw: str | None,
                    brand_normalized: str | None, item: dict[str, Any]):
        stmt = sqlite_insert(SpuMaster).values(
            spu_id=spu_id,
            brand_id=brand_normalized or spu_id,
            brand_name_raw=brand_raw,
            brand_name_normalized=brand_normalized,
            cid=item.get("cid", ""),
            category=item.get("category", ""),
            title=item.get("title"),
            first_seen_batch=item.get("batch_id"),
            last_seen_batch=item.get("batch_id"),
            is_active=True,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["spu_id"],
            set_={
                "brand_name_raw": stmt.excluded.brand_name_raw,
                "brand_name_normalized": stmt.excluded.brand_name_normalized,
                "title": stmt.excluded.title,
                "last_seen_batch": stmt.excluded.last_seen_batch,
                "is_active": True,
            },
        )
        conn.execute(stmt)

    def _upsert_sku(self, conn, spu_id: str, cumu_review: int, price: float):
        now = datetime.now(timezone.utc).isoformat()
        stmt = sqlite_insert(SkuDetail).values(
            sku_id=spu_id,  # demo: SPU = SKU
            spu_id=spu_id,
            price=price,
            cumu_review_count=cumu_review,
            review_count_updated_at=now,
            is_representative=True,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["sku_id"],
            set_={
                "cumu_review_count": stmt.excluded.cumu_review_count,
                "price": stmt.excluded.price,
                "review_count_updated_at": stmt.excluded.review_count_updated_at,
            },
        )
        conn.execute(stmt)

    def _upsert_monthly_delta(self, conn, spu_id: str, cumu_review: int,
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

        stmt = sqlite_insert(MonthlyDelta).values(
            batch_id=batch_id,
            month=month,
            spu_id=spu_id,
            cumu_review_count=cumu_review,
            prev_review_count=prev_count,
            delta=delta,
            negative_delta=negative,
            price_sampled=price,
            sales_value_proxy=sales_value,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["batch_id", "month", "spu_id"],
            set_={
                "cumu_review_count": stmt.excluded.cumu_review_count,
                "delta": stmt.excluded.delta,
                "negative_delta": stmt.excluded.negative_delta,
                "price_sampled": stmt.excluded.price_sampled,
                "sales_value_proxy": stmt.excluded.sales_value_proxy,
            },
        )
        conn.execute(stmt)

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
                if t.get("remove_parentheses"):
                    # 删除半角和全角括号及其中内容
                    result = re.sub(r"[\(（].*?[\)）]", "", result)
                if "remove_suffix" in t:
                    for suffix in t["remove_suffix"]:
                        if result.endswith(suffix):
                            result = result[:-len(suffix)]
                if t.get("unify_case") == "first_capital":
                    # 仅当长度 > 3 时做首字母大写归一
                    # 短品牌（如 P&G、KAO）保持原样，由 alias_mapping 处理
                    if result and len(result) > 3:
                        result = result[0].upper() + result[1:].lower()
                if "alias_mapping" in t:
                    # 大小写不敏感匹配
                    result_lower = result.lower() if result else ""
                    for alias, std in t["alias_mapping"].items():
                        if result_lower == alias.lower():
                            result = std
                            break

        return result.strip() if result else None
