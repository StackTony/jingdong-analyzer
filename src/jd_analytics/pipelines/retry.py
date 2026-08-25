"""
失败重试 Pipeline + retry_queue 队列辅助函数（spec §8.3 极简版）
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, select
from jd_analytics.models import RetryQueue
from jd_analytics.settings import DATABASE_URL

logger = logging.getLogger(__name__)


# 重试间隔（spec §8.3）：1h / 6h / 24h
RETRY_INTERVALS = [timedelta(hours=1), timedelta(hours=6), timedelta(hours=24)]


def enqueue_retry(url: str, batch_id: str | None, reason: str) -> None:
    """供中间件调用的 retry_queue 写入函数"""
    engine = create_engine(DATABASE_URL)
    now = datetime.now(timezone.utc)

    try:
        with engine.begin() as conn:
            existing = conn.execute(
                select(RetryQueue).where(RetryQueue.url == url)
            ).first()

            if existing:
                new_count = (existing.retry_count or 0) + 1
                interval_idx = min(new_count - 1, len(RETRY_INTERVALS) - 1)
                next_at = now + RETRY_INTERVALS[interval_idx]

                if new_count > 3:
                    logger.error(
                        f"Permanent failure: {url} after 3 retries (last: {reason})"
                    )
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
                        )
                    )
            else:
                next_at = now + RETRY_INTERVALS[0]
                conn.execute(
                    RetryQueue.__table__.insert().values(
                        url=url,
                        batch_id=batch_id or "unknown",
                        retry_count=1,
                        last_error=reason,
                        next_retry_at=next_at.isoformat(),
                    )
                )
    except Exception as e:
        logger.error(f"Failed to enqueue retry for {url}: {e}")


class RetryPipeline:
    """Spider 抛异常时入 retry_queue"""

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        return item
