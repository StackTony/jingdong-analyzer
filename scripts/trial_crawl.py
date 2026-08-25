"""
试爬脚本（spec §11 - MVP 第一周试爬验证）

1-2 品类 × 1000 URL 小规模试爬，校准反爬栈参数。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# 添加 src 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jd_analytics.cli import collect


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    )
    print("=" * 60)
    print("试爬验证（spec §11）")
    print("范围: 婴童纸尿裤 + 棉柔巾·绵柔巾 × 1000 URL")
    print("目标: 校准反爬栈 v2 参数")
    print("=" * 60)

    collect(trial=True)


if __name__ == "__main__":
    main()
