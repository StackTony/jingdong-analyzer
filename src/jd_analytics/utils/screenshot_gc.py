"""
截图 7 天自动清理（spec F001-ocr-route §3.4）

扫描 data/screenshots/，删除 mtime > 7 天的文件。
爬取前自动运行（可配置关闭）。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ScreenshotGC:
    """截图垃圾回收

    扫描 screenshot_path 下所有文件，删除 mtime > retention_days 的文件。
    空目录也一并清理。
    """

    def __init__(
        self,
        retention_days: int = 7,
        screenshot_path: str = "data/screenshots",
    ):
        self.retention_days = retention_days
        self.screenshot_path = Path(screenshot_path)

    def cleanup(self) -> dict[str, int]:
        """执行清理

        Returns:
            dict with keys: deleted_files, deleted_dirs, skipped, errors
        """
        if not self.screenshot_path.exists():
            logger.info(
                f"Screenshot path does not exist, skip GC: {self.screenshot_path}"
            )
            return {
                "deleted_files": 0,
                "deleted_dirs": 0,
                "skipped": 0,
                "errors": 0,
            }

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        cutoff_ts = cutoff.timestamp()

        stats = {"deleted_files": 0, "deleted_dirs": 0, "skipped": 0, "errors": 0}

        # 遍历所有文件
        all_files = list(self.screenshot_path.rglob("*"))
        files = [f for f in all_files if f.is_file()]
        dirs = sorted(
            [f for f in all_files if f.is_dir()],
            key=lambda d: len(d.parts),
            reverse=True,  # 先删最深的
        )

        for filepath in files:
            try:
                mtime = filepath.stat().st_mtime
                if mtime < cutoff_ts:
                    filepath.unlink()
                    stats["deleted_files"] += 1
                    logger.debug(f"Deleted screenshot: {filepath}")
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.warning(f"Failed to delete {filepath}: {e}")

        # 清理空目录
        for dirname in dirs:
            try:
                # 只有空目录才能删
                if not any(dirname.iterdir()):
                    dirname.rmdir()
                    stats["deleted_dirs"] += 1
                    logger.debug(f"Deleted empty dir: {dirname}")
            except Exception as e:
                stats["errors"] += 1
                logger.debug(f"Failed to remove dir {dirname}: {e}")

        logger.info(
            f"Screenshot GC done: "
            f"deleted={stats['deleted_files']} files, "
            f"{stats['deleted_dirs']} dirs, "
            f"skipped={stats['skipped']}, "
            f"errors={stats['errors']}"
        )
        return stats

    def get_stats(self) -> dict[str, Any]:
        """返回当前截图目录统计（不删除）"""
        if not self.screenshot_path.exists():
            return {
                "total_files": 0,
                "total_size_mb": 0.0,
                "oldest_file": None,
                "newest_file": None,
            }

        all_files = [f for f in self.screenshot_path.rglob("*") if f.is_file()]
        if not all_files:
            return {
                "total_files": 0,
                "total_size_mb": 0.0,
                "oldest_file": None,
                "newest_file": None,
            }

        total_size = sum(f.stat().st_size for f in all_files)
        mtimes = [f.stat().st_mtime for f in all_files]

        return {
            "total_files": len(all_files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "oldest_file": datetime.fromtimestamp(
                min(mtimes), tz=timezone.utc
            ).isoformat(),
            "newest_file": datetime.fromtimestamp(
                max(mtimes), tz=timezone.utc
            ).isoformat(),
        }


def main():
    """CLI 入口：手动跑 GC"""
    import argparse

    parser = argparse.ArgumentParser(description="截图 7 天清理")
    parser.add_argument(
        "--retention-days",
        type=int,
        default=7,
        help="保留天数（默认 7）",
    )
    parser.add_argument(
        "--path",
        default="data/screenshots",
        help="截图目录",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="只看统计不删除",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    gc = ScreenshotGC(
        retention_days=args.retention_days,
        screenshot_path=args.path,
    )

    if args.stats_only:
        stats = gc.get_stats()
        print("Screenshot stats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
    else:
        stats = gc.cleanup()
        print("GC result:")
        for k, v in stats.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
