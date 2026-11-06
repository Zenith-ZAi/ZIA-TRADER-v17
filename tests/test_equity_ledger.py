from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_manager import (
    DatabaseManager,
    EquityLedgerCaptureDisabled,
    EquityLedgerIdempotencyConflict,
    EquityLedgerValidationError,
)


EVENT_AT = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)


def _event(**overrides):
    values = {
        "account_id": "account-1",
        "source": "binance_spot",
        "source_event_id": "fill-001",
        "line_no": 0,
        "event_type": "trade_fill",
        "asset": "usdt",
        "amount": Decimal("-10.25"),
        "occurred_at": EVENT_AT,
        "reference_type": "order",
        "reference_id": "order-001",
    }
    values.update(overrides)
    return values


def _manager(tmp_path, *, enabled=False):
    manager = DatabaseManager(
        f"sqlite:///{tmp_path / 'equity-ledger.db'}",
        equity_ledger_capture_enabled=enabled,
    )
    manager.create_tables()
    return manager


def test_ledger_capture_is_disabled_by_default_and_does_not_change_verified_risk_contract(tmp_path):
    manager = _manager(tmp_path)
    try:
        with pytest.raises(EquityLedgerCaptureDisabled):
            manager.append_equity_ledger_event(**_event())
        assert manager.get_verified_risk_periods("account-1", EVENT_AT) is None
        assert manager.get_verified_trade_returns("account-1") is None
    finally:
        manager.engine.dispose()


def test_append_is_idempotent_and_conflicting_payload_is_never_overwritten(tmp_path):
    manager = _manager(tmp_path, enabled=True)
    try:
        first = manager.append_equity_ledger_event(**_event())
        duplicate = manager.append_equity_ledger_event(**_event(amount=Decimal("-10.2500")))

        assert first["status"] == "inserted"
        assert duplicate["status"] == "duplicate"
        assert duplicate["id"] == first["id"]
        assert duplicate["canonical_sha256"] == first["canonical_sha256"]
        assert len(manager.list_equity_ledger_events("account-1")) == 1

        with pytest.raises(EquityLedgerIdempotencyConflict):
            manager.append_equity_ledger_event(**_event(amount=Decimal("-10.26")))
        assert len(manager.list_equity_ledger_events("account-1")) == 1
    finally:
        manager.engine.dispose()


def test_identity_is_scoped_by_account_and_lines_support_multi_asset_events(tmp_path):
    manager = _manager(tmp_path, enabled=True)
    try:
        first = manager.append_equity_ledger_event(**_event())
        second = manager.append_equity_ledger_event(**_event(account_id="account-2"))
        third = manager.append_equity_ledger_event(**_event(line_no=1, asset="btc", amount=Decimal("0.0001")))

        assert len({first["id"], second["id"], third["id"]}) == 3
        assert len(manager.list_equity_ledger_events("account-1")) == 2
        assert len(manager.list_equity_ledger_events("account-2")) == 1
        assert manager.get_verified_risk_periods("account-1", EVENT_AT) is None
    finally:
        manager.engine.dispose()


def test_balance_snapshot_can_record_zero_but_delta_zero_and_untrusted_types_are_rejected(tmp_path):
    manager = _manager(tmp_path, enabled=True)
    try:
        snapshot = manager.append_equity_ledger_event(
            **_event(
                source_event_id="snapshot-001",
                event_type="balance_snapshot",
                asset="USD",
                amount=Decimal("0"),
                balance_component="free",
                reference_type=None,
                reference_id=None,
            )
        )
        assert snapshot["status"] == "inserted"

        invalid_payloads = (
            {"amount": Decimal("0")},
            {"amount": 0.1},
            {"amount": Decimal("NaN")},
            {"amount": Decimal("1.0000000000000000001")},
            {"occurred_at": datetime(2026, 10, 15, 12, 30)},
            {"event_type": "unknown"},
            {"balance_component": "free"},
        )
        for changes in invalid_payloads:
            with pytest.raises(EquityLedgerValidationError):
                manager.append_equity_ledger_event(**_event(**changes))
    finally:
        manager.engine.dispose()


def test_sqlite_round_trip_precision_loss_is_rejected_before_commit(tmp_path):
    manager = _manager(tmp_path, enabled=True)
    try:
        with pytest.raises(EquityLedgerValidationError, match="não preservou amount exatamente"):
            manager.append_equity_ledger_event(**_event(amount=Decimal("0.100000000000000001")))
        assert manager.list_equity_ledger_events("account-1") == []
    finally:
        manager.engine.dispose()


def test_ledger_reads_are_bounded_and_ordered_without_balance_aggregation(tmp_path):
    manager = _manager(tmp_path, enabled=True)
    try:
        manager.append_equity_ledger_event(**_event(source_event_id="fill-002", line_no=1, amount=Decimal("-10.25")))
        manager.append_equity_ledger_event(**_event(source_event_id="fill-001", line_no=0, amount=Decimal("-10.25")))

        rows = manager.list_equity_ledger_events("account-1", limit=1, offset=0)
        assert len(rows) == 1
        assert rows[0]["amount"] == Decimal("-10.25")
        assert rows[0]["amount_basis"] == "delta"
        assert rows[0]["occurred_at"].tzinfo == timezone.utc
        assert "equity" not in rows[0]
        with pytest.raises(ValueError, match="limit"):
            manager.list_equity_ledger_events("account-1", limit=501)
    finally:
        manager.engine.dispose()


def test_sqlite_replace_cannot_bypass_append_only_guard_on_managed_connection(tmp_path):
    manager = _manager(tmp_path, enabled=True)
    try:
        manager.append_equity_ledger_event(**_event())
        with manager.engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
            with pytest.raises(DBAPIError):
                connection.execute(
                    text(
                        "INSERT OR REPLACE INTO equity_ledger_v1 "
                        "(account_id, source, source_event_id, line_no, event_type, asset, amount, amount_basis, "
                        "balance_component, occurred_at, recorded_at, reference_type, reference_id, canonical_sha256) "
                        "VALUES (:account_id, :source, :event_id, 0, 'trade_fill', 'USDT', -999, 'delta', "
                        "NULL, '2026-10-15 12:30:00', '2026-10-15 12:31:00', 'order', 'order-001', :digest)"
                    ),
                    {
                        "account_id": "account-1",
                        "source": "binance_spot",
                        "event_id": "fill-001",
                        "digest": "b" * 64,
                    },
                )
        rows = manager.list_equity_ledger_events("account-1")
        assert len(rows) == 1
        assert rows[0]["amount"] == Decimal("-10.25")
    finally:
        manager.engine.dispose()


def test_postgresql_preserves_numeric_scale_and_rejects_mutation_when_configured():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL não configurada; precisão PostgreSQL será validada no CI")
    if not database_url.startswith("postgresql"):
        pytest.skip("teste de precisão NUMERIC requer PostgreSQL")

    account_id = f"ledger-pg-{uuid4().hex}"
    source_event_id = f"fill-{uuid4().hex}"
    exact_amount = Decimal("0.100000000000000001")
    manager = DatabaseManager(database_url, equity_ledger_capture_enabled=True)
    try:
        manager.create_tables()
        from sqlalchemy.orm import sessionmaker

        connection = manager.engine.connect()
        transaction = connection.begin()
        manager.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=connection,
            join_transaction_mode="create_savepoint",
        )
        try:
            # Append uses savepoints on this fixture connection; outer rollback
            # removes the immutable row from a potentially reusable TEST_DATABASE_URL.
            manager.append_equity_ledger_event(
                account_id=account_id,
                source="test_pg",
                source_event_id=source_event_id,
                line_no=0,
                event_type="trade_fill",
                asset="USDT",
                amount=exact_amount,
                occurred_at=EVENT_AT,
            )
            rows = manager.list_equity_ledger_events(account_id)
            assert len(rows) == 1
            assert rows[0]["amount"] == exact_amount

            for statement in (
                "UPDATE equity_ledger_v1 SET amount = 1 WHERE account_id = :account_id",
                "DELETE FROM equity_ledger_v1 WHERE account_id = :account_id",
                "TRUNCATE TABLE equity_ledger_v1",
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        if ":account_id" in statement:
                            connection.execute(text(statement), {"account_id": account_id})
                        else:
                            connection.execute(text(statement))
        finally:
            transaction.rollback()
            connection.close()
    finally:
        manager.engine.dispose()
