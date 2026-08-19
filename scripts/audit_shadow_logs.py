#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AIObservation, SystemLog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="sqlite:///./data/zia_trader.db")
    args = parser.parse_args()
    engine = create_engine(args.database_url, connect_args={"check_same_thread": False} if "sqlite" in args.database_url else {})
    session = sessionmaker(bind=engine)()
    try:
        logs = session.query(SystemLog).order_by(SystemLog.id.desc()).limit(20).all()
        observations = session.query(AIObservation).order_by(AIObservation.id.desc()).limit(20).all()
        print(json.dumps({
            "logs": [{"level": log.level, "module": log.module, "message": log.message} for log in logs],
            "observations": len(observations),
        }, ensure_ascii=False, indent=2))
    finally:
        session.close()


if __name__ == "__main__":
    main()
