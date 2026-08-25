"""
批次报告生成（spec §7.2）

抓取完成后自动生成报告，含覆盖率/异常/导出文件清单。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select, func, and_
from jd_analytics.models import (
    Batch, SpuMaster, MonthlyDelta, RetryQueue, AnomalyAlert
)
from jd_analytics.settings import DATABASE_URL

logger = logging.getLogger(__name__)


def generate_batch_report(batch_id: str) -> str:
    """生成批次报告并写入文件"""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        batch = conn.execute(
            select(Batch).where(Batch.batch_id == batch_id)
        ).first()
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")

        # 各品类 URL 数（按 spu_master.category）
        category_counts = conn.execute(
            select(SpuMaster.category, func.count())
            .join(MonthlyDelta, MonthlyDelta.spu_id == SpuMaster.spu_id)
            .where(MonthlyDelta.batch_id == batch_id)
            .group_by(SpuMaster.category)
        ).all()

        # 负值差值
        negative_count = conn.execute(
            select(func.count()).select_from(MonthlyDelta)
            .where(and_(
                MonthlyDelta.batch_id == batch_id,
                MonthlyDelta.negative_delta == True,  # noqa: E712
            ))
        ).scalar() or 0

        # 下架商品
        delisted_count = conn.execute(
            select(func.count()).select_from(SpuMaster)
            .where(and_(
                SpuMaster.last_seen_batch == batch_id,
                SpuMaster.is_active == False,  # noqa: E712
            ))
        ).scalar() or 0

        # 失败 URL（永久失败的 priority=-1）
        permanent_failures = conn.execute(
            select(func.count()).select_from(RetryQueue)
            .where(and_(
                RetryQueue.batch_id == batch_id,
                RetryQueue.priority == -1,
            ))
        ).scalar() or 0

        # 告警
        alerts = conn.execute(
            select(AnomalyAlert).where(AnomalyAlert.batch_id == batch_id)
        ).all()

    # 生成报告文本
    report_lines = [
        "=" * 60,
        f"批次报告: {batch_id}",
        "=" * 60,
        f"月份: {batch.month}",
        f"开始: {batch.started_at}",
        f"结束: {batch.finished_at or '(running)'}",
        f"覆盖率: {batch.coverage or '?'}",
        f"成功率: {(batch.success_rate or 0) * 100:.1f}%",
        f"总 URL: {batch.total_urls or '?'}",
        f"成功: {batch.successful_urls or '?'}",
        f"失败: {batch.failed_urls or '?'}",
        "",
        "各品类 URL 数:",
    ]
    for cat, cnt in category_counts:
        report_lines.append(f"  {cat:30s}: {cnt:6d}")

    report_lines.extend([
        "",
        "异常检测:",
        f"  负值差值      : {negative_count} 条",
        f"  下架商品      : {delisted_count} 条",
        f"  永久失败 URL : {permanent_failures} 条",
        f"  告警数        : {len(alerts)}",
    ])

    for alert in alerts:
        report_lines.append(
            f"    [{alert.severity}] {alert.alert_type}: {alert.description}"
        )

    # 导出文件清单
    exports_path = Path("data/exports")
    if exports_path.exists():
        report_lines.extend(["", "导出文件:"])
        for f in sorted(exports_path.glob(f"*_{batch.month}*")):
            report_lines.append(f"  {f}")

    report_lines.extend(["=" * 60])

    report_text = "\n".join(report_lines)

    # 写入文件
    report_path = Path("data/exports") / f"batch_report_{batch_id}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")

    # 更新 batch.report_path
    with engine.begin() as conn:
        conn.execute(
            Batch.__table__.update()
            .where(Batch.batch_id == batch_id)
            .values(report_path=str(report_path))
        )

    logger.info(f"Batch report generated: {report_path}")
    return str(report_path)
