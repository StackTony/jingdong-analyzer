"""
品牌 Top30 双榜聚合（spec §6.3 - Q3 拍板）

销量榜 + 销售额榜，各取前 30。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from jd_analytics.models import MonthlyDelta, SpuMaster, BrandAggregate
from jd_analytics.settings import DATABASE_URL

logger = logging.getLogger(__name__)


def aggregate_top30(batch_id: str, month: str) -> None:
    """为指定批次所有品类生成 Top30 双榜

    spec §2 修订后：
    - volume = cumu_review_count (语义变为 total_sales，京东接口直出)
    - value = volume × price_sampled (销售额估算)
    """
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # 取该批次所有品类的 SPU 销量 + 价格（spec §2 简化版）
        stmt = (
            select(
                SpuMaster.category,
                SpuMaster.brand_id,
                SpuMaster.brand_name_normalized,
                MonthlyDelta.cumu_review_count,  # 语义 = total_sales
                MonthlyDelta.price_sampled,
            )
            .join(SpuMaster, MonthlyDelta.spu_id == SpuMaster.spu_id)
            .where(MonthlyDelta.batch_id == batch_id)
            .where(SpuMaster.is_active == True)  # noqa: E712
        )
        rows = conn.execute(stmt).all()

    # 按品类 + 品牌聚合
    by_category: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"volume": 0, "value": 0.0, "name": ""})
    )
    for row in rows:
        cat = row.category
        brand_id = row.brand_id
        # cumu_review_count 语义为 total_sales，直接累加
        volume = max(row.cumu_review_count or 0, 0)
        price = row.price_sampled or 0.0
        value = volume * price  # 销售额估算
        by_category[cat][brand_id]["volume"] += volume
        by_category[cat][brand_id]["value"] += value
        by_category[cat][brand_id]["name"] = row.brand_name_normalized or brand_id

    # 各品类双榜各取前 30
    with engine.begin() as conn:
        for cat, brands in by_category.items():
            # 销量榜
            volume_sorted = sorted(
                brands.items(),
                key=lambda x: (-x[1]["volume"], x[0])  # 销量降序 + brand_id 字典序
            )[:30]
            # 销售额榜
            value_sorted = sorted(
                brands.items(),
                key=lambda x: (-x[1]["value"], x[0])
            )[:30]

            # 写入 brand_aggregates
            for rank, (brand_id, agg) in enumerate(volume_sorted, 1):
                _upsert_brand_agg(
                    conn, batch_id, month, cat, brand_id, agg["name"],
                    agg["volume"], agg["value"],
                    sales_volume_rank=rank, sales_value_rank=None,
                )
            for rank, (brand_id, agg) in enumerate(value_sorted, 1):
                _upsert_brand_agg(
                    conn, batch_id, month, cat, brand_id, agg["name"],
                    agg["volume"], agg["value"],
                    sales_volume_rank=None, sales_value_rank=rank,
                )

    logger.info(
        f"Aggregated Top30 dual-rank for batch={batch_id} month={month}: "
        f"{len(by_category)} categories"
    )


def _upsert_brand_agg(conn, batch_id, month, category, brand_id,
                      brand_name, volume, value,
                      sales_volume_rank, sales_value_rank):
    """upsert brand_aggregate（合并双榜字段）"""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    stmt = sqlite_insert(BrandAggregate).values(
        batch_id=batch_id,
        month=month,
        category=category,
        brand_id=brand_id,
        brand_name_normalized=brand_name,
        sales_volume_proxy=volume,
        sales_value_proxy=value,
        sales_volume_rank=sales_volume_rank,
        sales_value_rank=sales_value_rank,
    )
    # ON CONFLICT 更新已有行
    update_dict = {
        "sales_volume_proxy": stmt.excluded.sales_volume_proxy,
        "sales_value_proxy": stmt.excluded.sales_value_proxy,
        "brand_name_normalized": stmt.excluded.brand_name_normalized,
    }
    if sales_volume_rank is not None:
        update_dict["sales_volume_rank"] = sales_volume_rank
    if sales_value_rank is not None:
        update_dict["sales_value_rank"] = sales_value_rank
    stmt = stmt.on_conflict_do_update(
        index_elements=["batch_id", "month", "category", "brand_id"],
        set_=update_dict,
    )
    conn.execute(stmt)
