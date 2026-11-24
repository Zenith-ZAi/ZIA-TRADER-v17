"""Add tenant-scoped KMS credential envelopes and metadata-only audit.

Revision ID: f72c4a8e1d90
Revises: c3f1e2a9b7d4
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f72c4a8e1d90"
down_revision: Union[str, None] = "c3f1e2a9b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _canonical_uuid_check(column: str = "id") -> str:
    remaining = column
    for character in "0123456789abcdef-":
        remaining = f"replace({remaining}, '{character}', '')"
    return (
        f"length({column}) = 36 AND lower({column}) = {column} "
        f"AND substr({column}, 9, 1) = '-' AND substr({column}, 14, 1) = '-' "
        f"AND substr({column}, 19, 1) = '-' AND substr({column}, 24, 1) = '-' "
        f"AND length({remaining}) = 0"
    )


def _assert_empty_before_downgrade(bind) -> None:
    inspector = sa.inspect(bind)
    for table in ("credential_vault_audit_v1", "credential_vault_v1"):
        if inspector.has_table(table):
            count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            if count:
                raise RuntimeError(
                    "Downgrade blocked: credential vault contains data; "
                    "remove or export it explicitly before downgrade"
                )


def upgrade() -> None:
    op.create_table(
        "credential_vault_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("kms_key_arn", sa.String(length=512), nullable=False),
        sa.Column("encrypted_data_key", sa.LargeBinary(), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("updated_by_principal_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_account_v1.id"],
            name="fk_credential_vault_v1_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_principal_id"],
            ["principal_v1.id"],
            name="fk_credential_vault_v1_updated_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broker_account_id", name="uq_credential_vault_v1_account"),
        sa.CheckConstraint(
            _canonical_uuid_check(),
            name="ck_credential_vault_v1_id_canonical_uuid",
        ),
        sa.CheckConstraint("version >= 1", name="ck_credential_vault_v1_version_positive"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_credential_vault_v1_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND encrypted_data_key IS NOT NULL "
            "AND length(encrypted_data_key) > 0 AND nonce IS NOT NULL AND length(nonce) = 12 "
            "AND ciphertext IS NOT NULL AND length(ciphertext) >= 16) "
            "OR (status = 'revoked' AND encrypted_data_key IS NULL "
            "AND nonce IS NULL AND ciphertext IS NULL)",
            name="ck_credential_vault_v1_envelope_state",
        ),
    )
    op.create_table(
        "credential_vault_audit_v1",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=False),
        sa.Column("actor_principal_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_account_v1.id"],
            name="fk_credential_vault_audit_v1_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_principal_id"],
            ["principal_v1.id"],
            name="fk_credential_vault_audit_v1_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            _canonical_uuid_check(),
            name="ck_credential_vault_audit_v1_id_canonical_uuid",
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'rotated', 'accessed', 'revoked')",
            name="ck_credential_vault_audit_v1_event_type",
        ),
        sa.CheckConstraint(
            "credential_version >= 1",
            name="ck_credential_vault_audit_v1_version_positive",
        ),
    )
    op.create_index(
        "ix_credential_vault_audit_v1_account_time",
        "credential_vault_audit_v1",
        ["broker_account_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    _assert_empty_before_downgrade(bind)
    inspector = sa.inspect(bind)
    if inspector.has_table("credential_vault_audit_v1"):
        if any(
            index.get("name") == "ix_credential_vault_audit_v1_account_time"
            for index in inspector.get_indexes("credential_vault_audit_v1")
        ):
            op.drop_index(
                "ix_credential_vault_audit_v1_account_time",
                table_name="credential_vault_audit_v1",
            )
        op.drop_table("credential_vault_audit_v1")
    if inspector.has_table("credential_vault_v1"):
        op.drop_table("credential_vault_v1")
