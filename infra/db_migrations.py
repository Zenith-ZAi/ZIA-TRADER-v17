from __future__ import annotations

import zlib
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION_LOCK_ID = zlib.crc32(b"zia-trader-schema-migrations")


def upgrade_database(engine: Engine) -> None:
    """Aplica `alembic upgrade head`; serializa inicializações simultâneas em PostgreSQL."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    connection = engine.connect()
    lock_acquired = False
    try:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": _MIGRATION_LOCK_ID})
            connection.commit()
            lock_acquired = True
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    finally:
        config.attributes.pop("connection", None)
        if lock_acquired:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _MIGRATION_LOCK_ID})
                connection.commit()
            finally:
                connection.close()
        else:
            connection.close()
