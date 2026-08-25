"""
SQLAlchemy 数据模型（spec §4.1）

表结构：
- batches: 抓取批次
- spu_master: SPU 主数据
- sku_detail: SKU 明细
- monthly_deltas: 月度差值（按月分区）
- brand_aggregates: 品牌 Top30 双榜
- retry_queue: 重试队列
- selector_versions: 选择器版本
- anomaly_alerts: 异常告警
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    PrimaryKeyConstraint, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Batch(Base):
    """抓取批次（spec §4.1）"""
    __tablename__ = "batches"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    month: Mapped[str] = mapped_column(Text, nullable=False)
    coverage: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_urls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    successful_urls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_urls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remediation_window: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_remediation: Mapped[bool] = mapped_column(Boolean, default=False)
    report_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class SpuMaster(Base):
    """SPU 主数据（spec §4.1）"""
    __tablename__ = "spu_master"

    spu_id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    brand_name_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_name_normalized: Mapped[str | None] = mapped_column(
        Text, nullable=True, index=True
    )
    cid: Mapped[str] = mapped_column(String, nullable=False, index=True)
    category: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    representative_sku_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sku_detail.sku_id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_batch: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_batch: Mapped[str | None] = mapped_column(Text, nullable=True)


class SkuDetail(Base):
    """SKU 明细（spec §4.1）"""
    __tablename__ = "sku_detail"

    sku_id: Mapped[str] = mapped_column(String, primary_key=True)
    spu_id: Mapped[str] = mapped_column(
        String, ForeignKey("spu_master.spu_id"), nullable=False, index=True
    )
    package_spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumu_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_count_updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_representative: Mapped[bool] = mapped_column(Boolean, default=False)


class MonthlyDelta(Base):
    """月度差值（spec §4.1，按月分区）"""
    __tablename__ = "monthly_deltas"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    spu_id: Mapped[str] = mapped_column(String, primary_key=True)
    cumu_review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    negative_delta: Mapped[bool] = mapped_column(Boolean, default=False)
    price_sampled: Mapped[float | None] = mapped_column(Float, nullable=True)
    sales_value_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)


class BrandAggregate(Base):
    """品牌 Top30 双榜（spec §4.1，Q3 拍板）"""
    __tablename__ = "brand_aggregates"

    batch_id: Mapped[str] = mapped_column(String, primary_key=True)
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, primary_key=True)
    brand_id: Mapped[str] = mapped_column(String, primary_key=True)
    brand_name_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    sales_volume_proxy: Mapped[int] = mapped_column(Integer, nullable=False)
    sales_value_proxy: Mapped[float] = mapped_column(Float, nullable=False)
    sales_volume_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sales_value_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_brand_agg_month_cat", "month", "category"),
    )


class RetryQueue(Base):
    """重试队列（spec §8.3）"""
    __tablename__ = "retry_queue"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    batch_id: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)


class SelectorVersion(Base):
    """选择器版本（spec §12）"""
    __tablename__ = "selector_versions"

    version: Mapped[str] = mapped_column(String, primary_key=True)
    effective_from: Mapped[str] = mapped_column(Text, nullable=False)
    effective_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    selectors: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnomalyAlert(Base):
    """异常告警（spec §7.2, §7.3）"""
    __tablename__ = "anomaly_alerts"

    alert_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)  # info/warning/critical
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[str] = mapped_column(Text, nullable=False)
