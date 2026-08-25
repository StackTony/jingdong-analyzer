"""
失败重试 Pipeline + retry_queue 队列辅助函数（spec §8.3）
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, select
from jd_analytics.models import RetryQueue
from jd_analytics.settings import DATABASE_URL, RETRY_PRIORITY_MAP

logger = logging.getLogger(__name__)


# 重试间隔（spec §8.3）：1h / 6h / 24h
RETRY_INTERVALS = [timedelta(hours=1), timedelta(hours=6), timedelta(hours=24)]


def enqueue_retry(url: str, batch_id: str | None, reason: str) -> None:
    """供中间件调用的 retry_queue 写入函数"""
    engine = create_engine(DATABASE_URL)
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        existing = conn.execute(
            select(RetryQueue).where(RetryQueue.url == url)
        ).first()

        if existing:
            # 重试次数 +1，next_retry_at 推迟
            new_count = existing.retry_count + 1
            interval_idx = min(new_count - 1, len(RETRY_INTERVALS) - 1)
            next_at = now + RETRY_INTERVALS[interval_idx]

            if new_count > 3:
                # 超过 3 次 → permanent_failure，进 batch_report（spec §8.3）
                logger.error(f"Permanent failure: {url} after 3 retries (last: {reason})")
                # 标记为永久失败（priority=-1）
                conn.execute(
                    RetryQueue.__table__.update()
                    .where(RetryQueue.url == url)
                    .values(
                        retry_count=new_count,
                        last_error=reason,
                        next_retry_at=next_at.isoformat(),
                        priority=-1,
                    )
                )
            else:
                conn.execute(
                    RetryQueue.__table__.update()
                    .where(RetryQueue.url == url)
                    .values(
                        retry_count=new_count,
                        last_error=reason,
                        next_retry_at=next_at.isoformat(),
                        priority=RETRY_PRIORITY_MAP.get(reason, 3),
                    )
                )
        else:
            # 新失败
            next_at = now + RETRY_INTERVALS[0]
            conn.execute(
                RetryQueue.__table__.insert().values(
                    url=url,
                    batch_id=batch_id or "unknown",
                    retry_count=1,
                    last_error=reason,
                    next_retry_at=next_at.isoformat(),
                    priority=RETRY_PRIORITY_MAP.get(reason, 3),
                )
            )


class RetryPipeline:
    """Spider 抛异常时入 retry_queue"""

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        # 正常 item 不进 retry_queue
        return item
