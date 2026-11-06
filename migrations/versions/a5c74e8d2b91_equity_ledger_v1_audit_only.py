"""Add an opt-in append-only audit evidence ledger; it is not authoritative equity.

Revision ID: a5c74e8d2b91
Revises: 4f9a2c7d1b63
Create Date: 2026-11-05 11:58:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a5c74e8d2b91"
down_revision: Union[str, None] = "4f9a2c7d1b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "equity_ledger_v1"
INDEX = "ix_equity_ledger_v1_account_occurred"


def _ensure_table() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(TABLE):
        raise RuntimeError(f"Upgrade blocked: {TABLE} already exists before its Alembic revision")
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.String(length=160), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("amount_basis", sa.String(length=8), nullable=False),
        sa.Column("balance_component", sa.String(length=16), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_type", sa.String(length=32), nullable=True),
        sa.Column("reference_id", sa.String(length=160), nullable=True),
        sa.Column("canonical_sha256", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "account_id", "source", "source_event_id", "line_no",
            name="uq_equity_ledger_v1_event_identity",
        ),
        sa.CheckConstraint(
            "event_type IN ('balance_snapshot', 'trade_fill', 'fee', 'funding', 'cashflow', 'reconciliation_adjustment')",
            name="ck_equity_ledger_v1_event_type",
        ),
        sa.CheckConstraint(
            "(event_type = 'balance_snapshot' AND amount_basis = 'balance' AND balance_component IS NOT NULL) "
            "OR (event_type <> 'balance_snapshot' AND amount_basis = 'delta' AND balance_component IS NULL AND amount <> 0)",
            name="ck_equity_ledger_v1_amount_semantics",
        ),
        sa.CheckConstraint(
            "balance_component IS NULL OR length(trim(balance_component)) > 0",
            name="ck_equity_ledger_v1_component_nonempty",
        ),
        sa.CheckConstraint("line_no >= 0", name="ck_equity_ledger_v1_line_no"),
        sa.CheckConstraint(
            "length(trim(account_id)) > 0 AND length(trim(source)) > 0 "
            "AND length(trim(source_event_id)) > 0 AND length(trim(asset)) > 0",
            name="ck_equity_ledger_v1_identity_nonempty",
        ),
        sa.CheckConstraint("length(canonical_sha256) = 64", name="ck_equity_ledger_v1_hash_length"),
    )
    op.create_index(INDEX, TABLE, ["account_id", "occurred_at", "id"], unique=False)


def _install_immutability_guards() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA recursive_triggers = ON")
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_equity_ledger_v1_no_update "
            "BEFORE UPDATE ON equity_ledger_v1 BEGIN "
            "SELECT RAISE(ABORT, 'equity_ledger_v1 is append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER IF NOT EXISTS trg_equity_ledger_v1_no_delete "
            "BEFORE DELETE ON equity_ledger_v1 BEGIN "
            "SELECT RAISE(ABORT, 'equity_ledger_v1 is append-only'); END"
        )
        return
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION zia_equity_ledger_v1_immutable_guard() RETURNS trigger "
            "LANGUAGE plpgsql SET search_path = pg_catalog AS $$ "
            "BEGIN RAISE EXCEPTION 'equity_ledger_v1 is append-only' USING ERRCODE = '55000'; END; $$"
        )
        op.execute(
            "CREATE TRIGGER trg_equity_ledger_v1_no_update_delete "
            "BEFORE UPDATE OR DELETE ON equity_ledger_v1 FOR EACH ROW "
            "EXECUTE FUNCTION zia_equity_ledger_v1_immutable_guard()"
        )
        op.execute(
            "CREATE TRIGGER trg_equity_ledger_v1_no_truncate "
            "BEFORE TRUNCATE ON equity_ledger_v1 FOR EACH STATEMENT "
            "EXECUTE FUNCTION zia_equity_ledger_v1_immutable_guard()"
        )
        return
    raise RuntimeError(f"Dialeto não suportado para equity_ledger_v1: {bind.dialect.name}")


def upgrade() -> None:
    _ensure_table()
    _install_immutability_guards()


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(TABLE):
        if bind.dialect.name == "postgresql":
            bind.exec_driver_sql("LOCK TABLE equity_ledger_v1 IN ACCESS EXCLUSIVE MODE")
        elif bind.dialect.name == "sqlite":
            bind.exec_driver_sql("BEGIN EXCLUSIVE")
        row_count = bind.execute(sa.text("SELECT COUNT(*) FROM equity_ledger_v1")).scalar_one()
        if row_count:
            raise RuntimeError("Downgrade blocked: equity_ledger_v1 contains audit evidence")

    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_equity_ledger_v1_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_equity_ledger_v1_no_delete")
    elif bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_equity_ledger_v1_no_update_delete ON equity_ledger_v1")
        op.execute("DROP TRIGGER IF EXISTS trg_equity_ledger_v1_no_truncate ON equity_ledger_v1")
        op.execute("DROP FUNCTION IF EXISTS zia_equity_ledger_v1_immutable_guard()")
    if sa.inspect(bind).has_table(TABLE):
        op.drop_table(TABLE)
