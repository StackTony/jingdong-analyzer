"""
原始 HTML 冷存 Pipeline（spec §4.3 + 云长修正）

不入主库 → 落 Parquet 冷存，保留 90 天用于 debug。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from jd_analytics.settings import COLD_STORAGE_PATH, COLD_STORAGE_RETENTION_DAYS

logger = logging.getLogger(__name__)


class ColdStoragePipeline:
    """原始 HTML Parquet 冷存 + 90 天过期清理"""

    def __init__(self):
        self.base_path = Path(COLD_STORAGE_PATH)
        self.base_path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item: dict[str, Any], spider):
        if not item.get("raw_html"):
            # 实际生产中由 spider 在 parse_item 设置 item["raw_html"] = response.text
            return item

        batch_id = item.get("batch_id", "unknown")
        spu_id = item.get("spu_id", "unknown")
        sub_path = self.base_path / batch_id
        sub_path.mkdir(parents=True, exist_ok=True)

        file_path = sub_path / f"{spu_id}.html.parquet"
        table = pa.table({
            "spu_id": [spu_id],
            "batch_id": [batch_id],
            "url": [item.get("url")],
            "fetched_at": [datetime.now(timezone.utc).isoformat()],
            "html": [item["raw_html"]],
        })
        pq.write_table(table, file_path, compression="snappy")
        logger.debug(f"Cold-stored HTML: {file_path}")

        # 定期清理（每 100 条触发一次检查）
        if not hasattr(self, "_cleanup_counter"):
            self._cleanup_counter = 0
        self._cleanup_counter += 1
        if self._cleanup_counter % 100 == 0:
            self._cleanup_expired()

        return item

    def _cleanup_expired(self) -> None:
        """清理超过 retention_days 的冷存文件"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=COLD_STORAGE_RETENTION_DAYS)
        cutoff_ts = cutoff.timestamp()

        for batch_dir in self.base_path.iterdir():
            if not batch_dir.is_dir():
                continue
            # 用目录修改时间粗判
            if batch_dir.stat().st_mtime < cutoff_ts:
                for f in batch_dir.glob("*.parquet"):
                    f.unlink()
                batch_dir.rmdir()
                logger.info(f"Cleaned expired cold storage: {batch_dir}")
