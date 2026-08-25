"""
初始化数据库表 + 写入基线配置版本。

用法: python scripts/init_db.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import create_engine, select
from jd_analytics.models import Base, Batch, SelectorVersion
from jd_analytics.settings import DATABASE_URL


def init_db():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    print(f"Database initialized: {DATABASE_URL}")

    # 写入选择器 v1 版本记录
    selectors_path = (
        Path(__file__).parent.parent
        / "src" / "jd_analytics" / "config" / "selectors" / "v1.yaml"
    )
    if selectors_path.exists():
        import yaml
        with open(selectors_path, encoding="utf-8") as f:
            selectors_data = yaml.safe_load(f)

        with engine.begin() as conn:
            existing = conn.execute(
                select(SelectorVersion).where(SelectorVersion.version == "v1")
            ).first()
            if not existing:
                conn.execute(
                    SelectorVersion.__table__.insert().values(
                        version="v1",
                        effective_from=datetime.now(timezone.utc).isoformat(),
                        selectors=json.dumps(selectors_data["selectors"]),
                        created_by="郭嘉/奉孝 (@ragdoll-pa82)",
                        notes="初始版本",
                    )
                )
                print("Selector v1 registered")
            else:
                print("Selector v1 already registered")


if __name__ == "__main__":
    init_db()
