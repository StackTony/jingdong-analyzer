"""
CLI 入口（spec §5 - A 路线手动触发）

jd-collect  : 启动月度抓取
jd-export   : 导出 CSV/Parquet
jd-report   : 生成批次报告
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from jd_analytics.models import Base, Batch
from jd_analytics.settings import DATABASE_URL


def collect(
    month: str | None = None,
    trial: bool = False,
    mode: str = "json",
    dry_run: bool = False,
) -> None:
    """启动月度抓取（A 路线手动触发）

    Args:
        month: YYYY-MM，默认本月
        trial: 试爬模式（1-2 品类 × 少量页）
        mode: 抓取模式
            - "json": 监听 JSON 接口（默认，DrissionSpider）
            - "ocr":  整页截图 + PaddleOCR-VL 提取（OcrSpider）
        dry_run: 只验证代码路径，不实际访问京东
    """
    now = datetime.now(timezone.utc)
    month = month or now.strftime("%Y-%m")
    batch_id = now.isoformat(timespec="seconds").replace(":", "").replace("+", "")

    # 初始化数据库
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)

    # 记录批次开始
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    stmt = sqlite_insert(Batch).values(
        batch_id=batch_id,
        started_at=now.isoformat(),
        month=month,
        is_remediation=False,
    ).on_conflict_do_nothing(index_elements=["batch_id"])
    with engine.begin() as conn:
        conn.execute(stmt)

    # 根据模式启动 spider
    if mode == "ocr":
        from jd_analytics.spiders.ocr_spider import OcrSpider

        spider = OcrSpider(
            batch_id=batch_id,
            month=month,
            trial=trial,
            dry_run=dry_run,
        )
        results = spider.run()

        # 抓取完 → 聚合 Top30
        try:
            from jd_analytics.aggregator import aggregate_top30
            aggregate_top30(batch_id, month)
        except Exception as e:
            logging.getLogger(__name__).error(f"Aggregator failed: {e}")

        # 生成报告
        report(month=month, batch_id=batch_id)
        print(f"Done. batch_id={batch_id}, results={results}")
    else:
        # JSON 接口模式（原逻辑，用 DrissionSpider）
        from jd_analytics.spiders.drission_spider import DrissionSpider

        spider = DrissionSpider(
            batch_id=batch_id,
            month=month,
            trial=trial,
        )
        results = spider.run()

        try:
            from jd_analytics.aggregator import aggregate_top30
            aggregate_top30(batch_id, month)
        except Exception as e:
            logging.getLogger(__name__).error(f"Aggregator failed: {e}")

        report(month=month, batch_id=batch_id)
        print(f"Done. batch_id={batch_id}, results={results}")


def export(month: str, output_dir: str = "data/exports") -> None:
    """导出 Top30 双榜 CSV + 全量 Parquet"""
    from pathlib import Path
    import pandas as pd

    engine = create_engine(DATABASE_URL)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 双榜 CSV
    df = pd.read_sql(
        f"SELECT * FROM brand_aggregates WHERE month='{month}'",
        engine,
    )
    for rank_type in ["sales_volume", "sales_value"]:
        sub = (
            df[df[f"{rank_type}_rank"].notna()]
            .sort_values(["category", f"{rank_type}_rank"])
        )
        sub.to_csv(out / f"top30_{rank_type.replace('sales_', '')}_{month}.csv",
                   index=False, encoding="utf-8-sig")

    # 全量 Parquet
    full_df = pd.read_sql(
        f"SELECT * FROM monthly_deltas WHERE month='{month}'",
        engine,
    )
    full_df.to_parquet(out / f"full_{month}.parquet", compression="snappy", index=False)

    # methodology + usage_license
    _write_methodology(out, month)
    _write_usage_license(out, month)


def report(month: str | None = None, batch_id: str | None = None) -> None:
    """生成批次报告"""
    from jd_analytics.batch_report import generate_batch_report

    if not batch_id:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            from sqlalchemy import select
            stmt = select(Batch)
            if month:
                stmt = stmt.where(Batch.month == month)
            stmt = stmt.order_by(Batch.started_at.desc()).limit(1)
            batch = conn.execute(stmt).first()
            if not batch:
                print(f"No batch found for month={month}")
                sys.exit(1)
            batch_id = batch.batch_id

    path = generate_batch_report(batch_id)
    print(f"Report: {path}")


def _write_methodology(out: Path, month: str) -> None:
    """生成方法论声明（spec §2.4）"""
    text = f"""数据口径声明
============

月份: {month}

本数据集采集自京东公开商品页面，提供以下字段：
- 销量代理：本月累计评价数 - 上月累计评价数
- 销售额估算：销量代理 × 当前单价

局限性：
1. 销量代理不等于真实销量，受评价转化率（30-70%）影响，可能偏低 30-50%
2. 评价数存在滞后性，30 天窗口可能捕获 30-60 天前的购买行为
3. 退货删评、刷评干扰难以完全剔除

建议用途：
- 品牌相对位次变迁（A 涨 B 落）
- 长期趋势监测（月度变化方向）
- 新品牌崛起识别

不建议用途：
- 绝对销量数字（不能与京东商智真实数据对标）
- 短期波动分析（30 天窗口信号噪声比低）
"""
    (out / f"methodology_{month}.txt").write_text(text, encoding="utf-8")


def _write_usage_license(out: Path, month: str) -> None:
    """生成使用授权声明（spec §1.2 - Q6 商业用途）"""
    text = f"""数据使用授权声明
================

月份: {month}

本数据集经客户书面授权（见 docs/authorization.txt），允许用于商业用途。

授权范围：
- 京东公开页面的 11 品类商品/品牌数据
- 月度 Top30 排行榜及衍生分析

禁止：
- 将原始数据再分发至第三方
- 用于客户授权范围外的商业用途
- 用于违反《数据安全法》《反不正当竞争法》的行为

责任承担：
- 数据采集合规风险由客户承担（见书面授权函）

数据来源：京东公开商品页面
"""
    (out / f"usage_license_{month}.txt").write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="京东品牌分析 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="启动月度抓取")
    p_collect.add_argument("--month", help="YYYY-MM，默认本月")
    p_collect.add_argument("--trial", action="store_true", help="试爬模式（1-2 品类 × 少量页）")
    p_collect.add_argument(
        "--mode",
        choices=["json", "ocr"],
        default="json",
        help="抓取模式：json=监听接口（默认），ocr=截图+OCR",
    )
    p_collect.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证代码路径，不实际访问京东（ocr 模式专用）",
    )

    p_export = sub.add_parser("export", help="导出 CSV/Parquet")
    p_export.add_argument("--month", required=True, help="YYYY-MM")
    p_export.add_argument("--output-dir", default="data/exports")

    p_report = sub.add_parser("report", help="生成批次报告")
    p_report.add_argument("--month")
    p_report.add_argument("--batch-id")

    p_gc = sub.add_parser("gc", help="截图 7 天清理")
    p_gc.add_argument(
        "--stats-only",
        action="store_true",
        help="只看统计不删除",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.command == "collect":
        collect(
            month=args.month,
            trial=args.trial,
            mode=args.mode,
            dry_run=args.dry_run,
        )
    elif args.command == "export":
        export(month=args.month, output_dir=args.output_dir)
    elif args.command == "report":
        report(month=args.month, batch_id=args.batch_id)
    elif args.command == "gc":
        from jd_analytics.utils.screenshot_gc import ScreenshotGC
        from jd_analytics.settings import SCREENSHOT_PATH, SCREENSHOT_RETENTION_DAYS

        gc = ScreenshotGC(
            retention_days=SCREENSHOT_RETENTION_DAYS,
            screenshot_path=SCREENSHOT_PATH,
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
