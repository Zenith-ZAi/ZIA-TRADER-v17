from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DBAPIError

from database import get_engine, init_db
from database_manager import DatabaseManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "ledger_scope_v1",
    "ledger_fact_v1",
    "ledger_coverage_manifest_v1",
    "ledger_balance_snapshot_v1",
    "ledger_period_closure_v1",
}
BASE_REVISION = "c3f1e2a9b7d4"
TIMESTAMP = "2026-11-01 00:00:00+00:00"


def _migrate(tmp_path, monkeypatch):
    tmp_path.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{tmp_path / 'authoritative-ledger.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def _sqlite_guards(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA recursive_triggers = ON")
        cursor.close()

    return database_url, cfg, engine


def _seed_scope(connection, *, tenant_id: str, account_id: str, scope_id: str, environment: str = "testnet"):
    connection.execute(
        text(
            "INSERT INTO tenant_v1 (id, name, status, created_at) "
            "VALUES (:id, :name, 'active', :created_at)"
        ),
        {"id": tenant_id, "name": f"tenant-{tenant_id}", "created_at": TIMESTAMP},
    )
    connection.execute(
        text(
            "INSERT INTO broker_account_v1 "
            "(id, tenant_id, venue, environment, account_ref, status, created_at) "
            "VALUES (:id, :tenant_id, 'binance', :environment, :account_ref, 'active', :created_at)"
        ),
        {
            "id": account_id,
            "tenant_id": tenant_id,
            "environment": environment,
            "account_ref": f"ref-{account_id}",
            "created_at": TIMESTAMP,
        },
    )
    connection.execute(
        text(
            "INSERT INTO ledger_scope_v1 (id, broker_account_id, base_asset, created_at_utc) "
            "VALUES (:id, :account_id, 'USDT', :created_at)"
        ),
        {"id": scope_id, "account_id": account_id, "created_at": TIMESTAMP},
    )


def _insert_manifest(
    connection,
    scope_id: str,
    manifest_id: str,
    *,
    complete: bool = False,
    cursor_end: str | None = None,
):
    connection.execute(
        text(
            "INSERT INTO ledger_coverage_manifest_v1 "
            "(manifest_id, scope_id, endpoint, requested_at_utc, received_at_utc, cursor_start, cursor_end, "
            "coverage_start_utc, coverage_end_utc, expected_assets_json, complete, reconciliation_status) "
            "VALUES (:manifest_id, :scope_id, 'account/trades', :ts, :ts, 'cursor-a', :cursor_end, :ts, "
            "'2026-11-02 00:00:00+00:00', '[\"BTC\",\"USDT\"]', :complete, :status)"
        ),
        {
            "manifest_id": manifest_id,
            "scope_id": scope_id,
            "ts": TIMESTAMP,
            "cursor_end": cursor_end if cursor_end is not None else ("cursor-z" if complete else None),
            "complete": complete,
            "status": "complete" if complete else "pending",
        },
    )


def _insert_fill(connection, scope_id: str, *, source_event_id: str = "trade-1"):
    connection.execute(
        text(
            "INSERT INTO ledger_fact_v1 "
            "(id, scope_id, fact_type, source_event_id, source_line_no, asset, amount, occurred_at_utc, "
            "ingested_at_utc, venue_order_id, venue_trade_id, symbol, side, quantity, price, adapter_name, adapter_version) "
            "VALUES (:id, :scope_id, 'fill', :event_id, 0, 'BTC', 0.1, :ts, :ts, 'order-1', "
            "'trade-1', 'BTCUSDT', 'buy', 0.1, 50000, 'binance_testnet_readonly', 'v1')"
        ),
        {"id": str(uuid4()), "scope_id": scope_id, "event_id": source_event_id, "ts": TIMESTAMP},
    )


def test_migration_creates_scoped_append_only_financial_schema(tmp_path, monkeypatch):
    _, _, engine = _migrate(tmp_path, monkeypatch)
    try:
        assert TABLES <= set(inspect(engine).get_table_names())
        tenant_id, account_id, scope_id = (str(uuid4()) for _ in range(3))
        manifest_id = str(uuid4())
        with engine.begin() as connection:
            _seed_scope(connection, tenant_id=tenant_id, account_id=account_id, scope_id=scope_id)
            _insert_manifest(connection, scope_id, manifest_id)
            _insert_fill(connection, scope_id)

        with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                with connection.begin():
                    connection.execute(
                        text("UPDATE ledger_fact_v1 SET amount = 7 WHERE source_event_id = 'trade-1'")
                    )
            with pytest.raises(DBAPIError):
                with connection.begin():
                    connection.execute(
                        text("DELETE FROM ledger_fact_v1 WHERE source_event_id = 'trade-1'")
                    )
            assert connection.execute(text("SELECT COUNT(*) FROM ledger_fact_v1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_financial_constraints_reject_unclosed_coverage_and_incomplete_facts(tmp_path, monkeypatch):
    _, _, engine = _migrate(tmp_path, monkeypatch)
    try:
        tenant_id, account_id, scope_id = (str(uuid4()) for _ in range(3))
        with engine.begin() as connection:
            _seed_scope(connection, tenant_id=tenant_id, account_id=account_id, scope_id=scope_id)
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    _insert_manifest(connection, scope_id, str(uuid4()), complete=True, cursor_end="")
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO ledger_fact_v1 "
                            "(id, scope_id, fact_type, source_event_id, source_line_no, asset, amount, "
                            "occurred_at_utc, ingested_at_utc, adapter_name, adapter_version) "
                            "VALUES (:id, :scope_id, 'fill', 'bad-fill', 0, 'BTC', 0.1, :ts, :ts, 'test', 'v1')"
                        ),
                        {"id": str(uuid4()), "scope_id": scope_id, "ts": TIMESTAMP},
                    )
            opening_manifest_id, closing_manifest_id = str(uuid4()), str(uuid4())
            _insert_manifest(connection, scope_id, opening_manifest_id)
            _insert_manifest(connection, scope_id, closing_manifest_id)
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO ledger_period_closure_v1 "
                            "(id, scope_id, period_start_utc, period_end_utc, opening_manifest_id, "
                            "closing_manifest_id, fact_watermark_utc, fact_count, missing_count, late_count, "
                            "fees_included, funding_included, cashflows_reconciled, balances_reconciled, "
                            "status, recorded_at_utc, closed_at_utc) VALUES "
                            "(:id, :scope_id, :start, :end, :opening, :closing, :end, 0, 0, 0, "
                            "true, true, true, true, 'closed', :end, :end)"
                        ),
                        {
                            "id": str(uuid4()),
                            "scope_id": scope_id,
                            "start": TIMESTAMP,
                            "end": "2026-11-02 00:00:00+00:00",
                            "opening": opening_manifest_id,
                            "closing": closing_manifest_id,
                        },
                    )
            assert connection.execute(
                text("SELECT COUNT(*) FROM ledger_coverage_manifest_v1 WHERE scope_id = :scope_id"),
                {"scope_id": scope_id},
            ).scalar_one() == 2
    finally:
        engine.dispose()


def test_migration_refuses_preexisting_schema_and_downgrade_with_evidence(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'preexisting-authoritative-ledger.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(cfg, BASE_REVISION)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE ledger_fact_v1 (id INTEGER PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="already exist before their Alembic revision"):
            command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert [column[1] for column in connection.exec_driver_sql("PRAGMA table_info(ledger_fact_v1)")] == ["id"]
    finally:
        engine.dispose()

    database_url, cfg, engine = _migrate(tmp_path / "downgrade", monkeypatch)
    try:
        tenant_id, account_id, scope_id = (str(uuid4()) for _ in range(3))
        with engine.begin() as connection:
            _seed_scope(connection, tenant_id=tenant_id, account_id=account_id, scope_id=scope_id)
        with pytest.raises(RuntimeError, match="tables contain evidence"):
            command.downgrade(cfg, BASE_REVISION)
    finally:
        engine.dispose()


@pytest.mark.parametrize("creation_path", ["database_manager", "init_db"])
def test_sqlite_create_all_paths_enforce_ledger_integrity_and_guards(tmp_path, monkeypatch, creation_path):
    monkeypatch.setenv("ENVIRONMENT", "development")
    database_url = f"sqlite:///{tmp_path / f'{creation_path}-ledger.db'}"
    manager = None
    if creation_path == "database_manager":
        manager = DatabaseManager(database_url)
        manager.create_tables()
        engine = manager.engine
    else:
        engine = get_engine(database_url)
        init_db(engine)

    try:
        with engine.connect() as first_connection, engine.connect() as second_connection:
            for connection in (first_connection, second_connection):
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
                assert connection.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
            triggers = first_connection.execute(
                text("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_ledger_%'")
            ).scalar_one()
            assert triggers == 10

        tenant_a, account_a, scope_a = (str(uuid4()) for _ in range(3))
        tenant_b, account_b, scope_b = (str(uuid4()) for _ in range(3))
        manifest_a, manifest_b = str(uuid4()), str(uuid4())
        with engine.begin() as connection:
            _seed_scope(connection, tenant_id=tenant_a, account_id=account_a, scope_id=scope_a)
            _seed_scope(connection, tenant_id=tenant_b, account_id=account_b, scope_id=scope_b)
            _insert_manifest(connection, scope_a, manifest_a)
            _insert_manifest(connection, scope_b, manifest_b)

            # Exact decimal equality belongs in a future Decimal writer, not in
            # SQLite's approximate NUMERIC-affinity CHECK expression.
            connection.execute(
                text(
                    "INSERT INTO ledger_balance_snapshot_v1 "
                    "(id, scope_id, snapshot_id, asset, free_amount, locked_amount, total_amount, "
                    "as_of_utc, ingested_at_utc, source_cursor, coverage_manifest_id) "
                    "VALUES (:id, :scope, :snapshot, 'USDT', '0.1', '0.2', '0.3', :ts, :ts, 'c1', :manifest)"
                ),
                {
                    "id": str(uuid4()),
                    "scope": scope_a,
                    "snapshot": str(uuid4()),
                    "ts": TIMESTAMP,
                    "manifest": manifest_a,
                },
            )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO ledger_balance_snapshot_v1 "
                            "(id, scope_id, snapshot_id, asset, free_amount, locked_amount, total_amount, "
                            "as_of_utc, ingested_at_utc, source_cursor, coverage_manifest_id) "
                            "VALUES (:id, :scope, :snapshot, 'USDT', -1, 0, 0, :ts, :ts, 'c2', :manifest)"
                        ),
                        {
                            "id": str(uuid4()),
                            "scope": scope_a,
                            "snapshot": str(uuid4()),
                            "ts": TIMESTAMP,
                            "manifest": manifest_a,
                        },
                    )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO ledger_balance_snapshot_v1 "
                            "(id, scope_id, snapshot_id, asset, free_amount, locked_amount, total_amount, "
                            "as_of_utc, ingested_at_utc, source_cursor, coverage_manifest_id) "
                            "VALUES (:id, :scope, :snapshot, 'USDT', 0.1, 0, 0.1, :ts, :ts, 'c3', :manifest)"
                        ),
                        {
                            "id": str(uuid4()),
                            "scope": scope_a,
                            "snapshot": str(uuid4()),
                            "ts": TIMESTAMP,
                            "manifest": manifest_b,
                        },
                    )

            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO ledger_fact_v1 "
                            "(id, scope_id, fact_type, source_event_id, source_line_no, asset, amount, "
                            "occurred_at_utc, ingested_at_utc, adapter_name, adapter_version) "
                            "VALUES (:id, :scope, 'fill', 'incomplete-fill', 0, 'BTC', 0.1, :ts, :ts, 'test', 'v1')"
                        ),
                        {"id": str(uuid4()), "scope": scope_a, "ts": TIMESTAMP},
                    )

            _insert_fill(connection, scope_a)

        with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                with connection.begin():
                    connection.execute(
                        text("UPDATE ledger_fact_v1 SET amount = 7 WHERE source_event_id = 'trade-1'")
                    )
            with pytest.raises(DBAPIError):
                with connection.begin():
                    connection.execute(text("DELETE FROM ledger_fact_v1 WHERE source_event_id = 'trade-1'"))
            assert connection.execute(
                text("SELECT COUNT(*) FROM ledger_balance_snapshot_v1")
            ).scalar_one() == 1
    finally:
        if manager is not None:
            manager.engine.dispose()
        else:
            engine.dispose()
