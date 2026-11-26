"""Add schema-only foundation for scoped authoritative-ledger evidence.

Revision ID: d8a11c4e52f0
Revises: c3f1e2a9b7d4
Create Date: 2026-11-26

This migration creates storage contracts only. It does not add an exchange
producer, reconciliation writer, verified getter, or risk/sizing consumer.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8a11c4e52f0"
down_revision: Union[str, None] = "c3f1e2a9b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "ledger_scope_v1",
    "ledger_coverage_manifest_v1",
    "ledger_balance_snapshot_v1",
    "ledger_fact_v1",
    "ledger_period_closure_v1",
)
APPEND_ONLY_TABLES = TABLES


def _ensure_tables_absent() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = [table for table in TABLES if inspector.has_table(table)]
    if existing:
        raise RuntimeError(
            "Upgrade blocked: authoritative-ledger tables already exist before their Alembic revision: "
            + ", ".join(existing)
        )


def _create_tables() -> None:
    op.create_table(
        "ledger_scope_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=False),
        sa.Column("base_asset", sa.String(length=32), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["broker_account_id"], ["broker_account_v1.id"],
            name="fk_ledger_scope_v1_broker_account", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_account_id", name="uq_ledger_scope_v1_broker_account"),
        sa.CheckConstraint(
            "length(id) = 36 AND lower(id) = id AND substr(id, 9, 1) = '-' "
            "AND substr(id, 14, 1) = '-' AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'",
            name="ck_ledger_scope_v1_id_uuid",
        ),
        sa.CheckConstraint("length(trim(base_asset)) > 0", name="ck_ledger_scope_v1_base_asset"),
    )

    op.create_table(
        "ledger_coverage_manifest_v1",
        sa.Column("manifest_id", sa.String(length=36), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("requested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor_start", sa.String(length=255), nullable=True),
        sa.Column("cursor_end", sa.String(length=255), nullable=True),
        sa.Column("coverage_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_assets_json", sa.JSON(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reconciliation_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["ledger_scope_v1.id"],
            name="fk_ledger_coverage_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("manifest_id"),
        sa.UniqueConstraint("scope_id", "manifest_id", name="uq_ledger_coverage_manifest_scope_id"),
        sa.CheckConstraint("length(trim(endpoint)) > 0", name="ck_ledger_coverage_endpoint"),
        sa.CheckConstraint(
            "reconciliation_status IN ('pending', 'attention')",
            name="ck_ledger_coverage_reconciliation_status",
        ),
        sa.CheckConstraint("coverage_start_utc < coverage_end_utc", name="ck_ledger_coverage_interval"),
        sa.CheckConstraint("complete = false", name="ck_ledger_coverage_not_verified_in_foundation"),
    )

    op.create_table(
        "ledger_balance_snapshot_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("free_amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("locked_amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_cursor", sa.String(length=255), nullable=False),
        sa.Column("coverage_manifest_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope_id", "coverage_manifest_id"],
            ["ledger_coverage_manifest_v1.scope_id", "ledger_coverage_manifest_v1.manifest_id"],
            name="fk_ledger_balance_coverage_manifest", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_id", "snapshot_id", "asset", name="uq_ledger_balance_scope_snapshot_asset"),
        sa.CheckConstraint("length(trim(asset)) > 0", name="ck_ledger_balance_asset"),
        sa.CheckConstraint(
            "free_amount >= 0 AND locked_amount >= 0 AND total_amount >= 0",
            name="ck_ledger_balance_nonnegative",
        ),
        sa.CheckConstraint("length(trim(source_cursor)) > 0", name="ck_ledger_balance_cursor"),
    )

    op.create_table(
        "ledger_fact_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("fact_type", sa.String(length=16), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=False),
        sa.Column("source_line_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_sequence", sa.BigInteger(), nullable=True),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_order_id", sa.String(length=160), nullable=True),
        sa.Column("venue_order_id", sa.String(length=160), nullable=True),
        sa.Column("venue_trade_id", sa.String(length=160), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("fee_asset", sa.String(length=32), nullable=True),
        sa.Column("fee_amount", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("funding_period_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_period_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_rate", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("cashflow_kind", sa.String(length=16), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("adapter_name", sa.String(length=64), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("raw_evidence_ref", sa.String(length=512), nullable=True),
        sa.Column("raw_evidence_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["scope_id"], ["ledger_scope_v1.id"],
            name="fk_ledger_fact_scope", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_id", "fact_type", "source_event_id", "source_line_no",
            name="uq_ledger_fact_scope_event_line",
        ),
        sa.CheckConstraint("fact_type IN ('fill', 'fee', 'funding', 'cashflow')", name="ck_ledger_fact_type"),
        sa.CheckConstraint(
            "length(trim(source_event_id)) > 0 AND length(trim(asset)) > 0 "
            "AND length(trim(adapter_name)) > 0 AND length(trim(adapter_version)) > 0",
            name="ck_ledger_fact_identity_nonempty",
        ),
        sa.CheckConstraint("source_line_no >= 0", name="ck_ledger_fact_line_no"),
        sa.CheckConstraint("amount <> 0", name="ck_ledger_fact_nonzero_amount"),
        sa.CheckConstraint(
            "(fact_type = 'fill' AND venue_order_id IS NOT NULL AND length(trim(venue_order_id)) > 0 "
            "AND venue_trade_id IS NOT NULL AND length(trim(venue_trade_id)) > 0 "
            "AND symbol IS NOT NULL AND length(trim(symbol)) > 0 AND side IS NOT NULL "
            "AND side IN ('buy', 'sell') AND quantity IS NOT NULL AND quantity > 0 "
            "AND price IS NOT NULL AND price > 0) OR "
            "(fact_type = 'fee' AND fee_asset IS NOT NULL AND length(trim(fee_asset)) > 0 "
            "AND fee_amount IS NOT NULL AND fee_amount <> 0) OR "
            "(fact_type = 'funding' AND funding_period_start_utc IS NOT NULL "
            "AND funding_period_end_utc IS NOT NULL AND funding_period_start_utc < funding_period_end_utc) OR "
            "(fact_type = 'cashflow' AND cashflow_kind IS NOT NULL "
            "AND cashflow_kind IN ('deposit', 'withdrawal', 'transfer') "
            "AND external_reference IS NOT NULL AND length(trim(external_reference)) > 0)",
            name="ck_ledger_fact_type_required_fields",
        ),
        sa.CheckConstraint(
            "raw_evidence_sha256 IS NULL OR length(raw_evidence_sha256) = 64",
            name="ck_ledger_fact_raw_digest_length",
        ),
    )
    op.create_index(
        "ix_ledger_fact_scope_occurred", "ledger_fact_v1", ["scope_id", "occurred_at_utc", "id"], unique=False
    )

    op.create_table(
        "ledger_period_closure_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("period_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opening_manifest_id", sa.String(length=36), nullable=False),
        sa.Column("closing_manifest_id", sa.String(length=36), nullable=False),
        sa.Column("fact_watermark_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("late_count", sa.Integer(), nullable=False),
        sa.Column("fees_included", sa.Boolean(), nullable=False),
        sa.Column("funding_included", sa.Boolean(), nullable=False),
        sa.Column("cashflows_reconciled", sa.Boolean(), nullable=False),
        sa.Column("balances_reconciled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["scope_id", "opening_manifest_id"],
            ["ledger_coverage_manifest_v1.scope_id", "ledger_coverage_manifest_v1.manifest_id"],
            name="fk_ledger_closure_opening_manifest", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scope_id", "closing_manifest_id"],
            ["ledger_coverage_manifest_v1.scope_id", "ledger_coverage_manifest_v1.manifest_id"],
            name="fk_ledger_closure_closing_manifest", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("period_start_utc < period_end_utc", name="ck_ledger_closure_period"),
        sa.CheckConstraint(
            "fact_count >= 0 AND missing_count >= 0 AND late_count >= 0",
            name="ck_ledger_closure_counts",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'attention')",
            name="ck_ledger_closure_not_verified_in_foundation",
        ),
        sa.CheckConstraint(
            "closed_at_utc IS NULL",
            name="ck_ledger_closure_no_verified_timestamp_in_foundation",
        ),
    )
    op.create_index(
        "ix_ledger_closure_scope_period",
        "ledger_period_closure_v1",
        ["scope_id", "period_start_utc", "period_end_utc"],
        unique=False,
    )


def _install_immutability_guards() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("PRAGMA recursive_triggers = ON")
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
                f"BEFORE UPDATE ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'authoritative ledger evidence is append-only'); END"
            )
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
                f"BEFORE DELETE ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'authoritative ledger evidence is append-only'); END"
            )
        return
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION zia_authoritative_ledger_v1_immutable_guard() RETURNS trigger "
            "LANGUAGE plpgsql SET search_path = pg_catalog AS $$ "
            "BEGIN RAISE EXCEPTION 'authoritative ledger evidence is append-only' "
            "USING ERRCODE = '55000'; END; $$"
        )
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"CREATE TRIGGER trg_{table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION zia_authoritative_ledger_v1_immutable_guard()"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
                "FOR EACH STATEMENT EXECUTE FUNCTION zia_authoritative_ledger_v1_immutable_guard()"
            )
        return
    raise RuntimeError(f"Unsupported dialect for authoritative ledger foundation: {bind.dialect.name}")


def upgrade() -> None:
    _ensure_tables_absent()
    _create_tables()
    _install_immutability_guards()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    present = [table for table in TABLES if inspector.has_table(table)]
    if present:
        if len(present) != len(TABLES):
            raise RuntimeError("Downgrade blocked: authoritative-ledger schema is incomplete")
        if bind.dialect.name == "postgresql":
            for table in reversed(TABLES):
                bind.exec_driver_sql(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
        elif bind.dialect.name == "sqlite":
            bind.exec_driver_sql("BEGIN EXCLUSIVE")
        for table in TABLES:
            if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
                raise RuntimeError("Downgrade blocked: authoritative-ledger tables contain evidence")

    if bind.dialect.name == "sqlite":
        for table in APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    elif bind.dialect.name == "postgresql":
        for table in APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update_delete ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}")
        op.execute("DROP FUNCTION IF EXISTS zia_authoritative_ledger_v1_immutable_guard()")

    for table in reversed(TABLES):
        if sa.inspect(bind).has_table(table):
            op.drop_table(table)
