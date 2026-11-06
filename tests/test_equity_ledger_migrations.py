from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _migrate_ledger(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'equity-ledger-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    return database_url, cfg


def _insert_snapshot(connection):
    connection.execute(
        text(
            "INSERT INTO equity_ledger_v1 "
            "(account_id, source, source_event_id, line_no, event_type, asset, amount, amount_basis, "
            "balance_component, occurred_at, recorded_at, reference_type, reference_id, canonical_sha256) "
            "VALUES ('account-1', 'binance_spot', 'snapshot-1', 0, 'balance_snapshot', 'USDT', 0, 'balance', "
            "'free', '2026-10-15 12:30:00+00:00', '2026-10-15 12:31:00+00:00', NULL, NULL, :digest)"
        ),
        {"digest": "a" * 64},
    )


def test_migration_blocks_update_delete_and_downgrade_with_evidence(tmp_path, monkeypatch):
    database_url, cfg = _migrate_ledger(tmp_path, monkeypatch)
    engine = create_engine(database_url)
    try:
        connection = engine.connect()
        transaction = connection.begin()
        try:
            _insert_snapshot(connection)
            for statement in (
                "UPDATE equity_ledger_v1 SET amount = 999 WHERE source_event_id = 'snapshot-1'",
                "DELETE FROM equity_ledger_v1 WHERE source_event_id = 'snapshot-1'",
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(text(statement))
        finally:
            transaction.rollback()
            connection.close()

        with engine.begin() as connection:
            _insert_snapshot(connection)
        with pytest.raises(RuntimeError, match="Downgrade blocked: equity_ledger_v1 contains audit evidence"):
            command.downgrade(cfg, "4f9a2c7d1b63")

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM equity_ledger_v1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_upgrade_refuses_to_adopt_preexisting_ledger_table(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'preexisting-ledger.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(cfg, "4f9a2c7d1b63")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE equity_ledger_v1 (id INTEGER PRIMARY KEY)"))

        with pytest.raises(RuntimeError, match="already exists before its Alembic revision"):
            command.upgrade(cfg, "head")

        with engine.connect() as connection:
            columns = connection.exec_driver_sql("PRAGMA table_info(equity_ledger_v1)").all()
            assert [column[1] for column in columns] == ["id"]
    finally:
        engine.dispose()
