"""Add the additive client-scope identity foundation.

Revision ID: c3f1e2a9b7d4
Revises: a5c74e8d2b91
Create Date: 2026-11-19

This revision deliberately creates no authorization policy, RLS policy,
credential store, order ledger, or compatibility view for legacy accounts.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f1e2a9b7d4"
down_revision: Union[str, None] = "a5c74e8d2b91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "tenant_v1",
    "principal_v1",
    "tenant_membership_v1",
    "broker_account_v1",
)
BROKER_TENANT_INDEX = "ix_broker_account_v1_tenant_id"


_UUID_CHECKS = {
    "tenant_v1": (
        "length(id) = 36 AND lower(id) = id "
        "AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-' "
        "AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'"
    ),
    "principal_v1": (
        "length(id) = 36 AND lower(id) = id "
        "AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-' "
        "AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'"
    ),
    "broker_account_v1": (
        "length(id) = 36 AND lower(id) = id "
        "AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-' "
        "AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'"
    ),
}


def _ensure_no_preexisting_tables(bind) -> None:
    inspector = sa.inspect(bind)
    existing = [table for table in TABLES if inspector.has_table(table)]
    if existing:
        names = ", ".join(existing)
        raise RuntimeError(
            "Upgrade blocked: client-scope tables already exist before their "
            f"Alembic revision: {names}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_no_preexisting_tables(bind)

    op.create_table(
        "tenant_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint(_UUID_CHECKS["tenant_v1"], name="ck_tenant_v1_id_canonical_uuid"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_tenant_v1_name_nonempty"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_tenant_v1_status"),
    )
    op.create_table(
        "principal_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_principal_v1_issuer_subject"),
        sa.CheckConstraint(_UUID_CHECKS["principal_v1"], name="ck_principal_v1_id_canonical_uuid"),
        sa.CheckConstraint(
            "length(trim(issuer)) > 0 AND length(trim(subject)) > 0",
            name="ck_principal_v1_identity_nonempty",
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_principal_v1_status"),
    )
    op.create_table(
        "tenant_membership_v1",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principal_v1.id"],
            name="fk_tenant_membership_v1_principal",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant_v1.id"],
            name="fk_tenant_membership_v1_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "principal_id"),
        sa.CheckConstraint(
            "role IN ('viewer', 'trader', 'admin')",
            name="ck_tenant_membership_v1_role",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_tenant_membership_v1_status",
        ),
    )
    op.create_table(
        "broker_account_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("venue", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("account_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant_v1.id"],
            name="fk_broker_account_v1_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue",
            "environment",
            "account_ref",
            name="uq_broker_account_v1_venue_environment_ref",
        ),
        sa.CheckConstraint(_UUID_CHECKS["broker_account_v1"], name="ck_broker_account_v1_id_canonical_uuid"),
        sa.CheckConstraint(
            "length(trim(venue)) > 0 AND length(trim(environment)) > 0 "
            "AND length(trim(account_ref)) > 0",
            name="ck_broker_account_v1_identity_nonempty",
        ),
        sa.CheckConstraint(
            "environment IN ('paper', 'testnet', 'demo', 'live')",
            name="ck_broker_account_v1_environment",
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_broker_account_v1_status"),
    )
    op.create_index(BROKER_TENANT_INDEX, "broker_account_v1", ["tenant_id"], unique=False)


def _assert_empty_before_downgrade(bind) -> None:
    inspector = sa.inspect(bind)
    present = [table for table in TABLES if inspector.has_table(table)]
    if not present:
        return
    if set(present) != set(TABLES):
        missing = ", ".join(table for table in TABLES if table not in present)
        raise RuntimeError(
            "Downgrade blocked: client-scope tables are incomplete; "
            f"missing: {missing}"
        )

    for table in TABLES:
        row_count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        if row_count:
            raise RuntimeError(
                "Downgrade blocked: client-scope tables contain data; "
                "remove it explicitly before downgrade"
            )


def downgrade() -> None:
    bind = op.get_bind()
    _assert_empty_before_downgrade(bind)
    inspector = sa.inspect(bind)
    if not all(inspector.has_table(table) for table in TABLES):
        return

    if any(index.get("name") == BROKER_TENANT_INDEX for index in inspector.get_indexes("broker_account_v1")):
        op.drop_index(BROKER_TENANT_INDEX, table_name="broker_account_v1")
    # Drop children before parents so the declared FKs remain valid on both
    # SQLite (when foreign_keys=ON) and PostgreSQL.
    op.drop_table("broker_account_v1")
    op.drop_table("tenant_membership_v1")
    op.drop_table("principal_v1")
    op.drop_table("tenant_v1")
