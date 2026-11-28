"""Persist WebAuthn public credentials and single-use ceremony challenges.
Revision ID: e8c4b70d2a91
Revises: c3f1e2a9b7d4
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e8c4b70d2a91"
down_revision: Union[str, None] = "c3f1e2a9b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "passkey_credentials",
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("username", sa.String(length=256), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("transports", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("credential_id"),
        sa.UniqueConstraint("username", name="uq_passkey_credentials_username"),
    )
    op.create_index("ix_passkey_credentials_username", "passkey_credentials", ["username"], unique=False)
    op.create_table(
        "passkey_challenges",
        sa.Column("challenge_hash", sa.LargeBinary(), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("username", sa.String(length=256), nullable=False),
        sa.Column("ceremony", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ceremony IN ('registration', 'authentication')", name="ck_passkey_challenges_ceremony"),
        sa.PrimaryKeyConstraint("challenge_hash"),
    )
    op.create_index("ix_passkey_challenges_username", "passkey_challenges", ["username"], unique=False)
    op.create_index("ix_passkey_challenges_expires_at", "passkey_challenges", ["expires_at"], unique=False)


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in ("passkey_credentials", "passkey_challenges"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")).first():
            raise RuntimeError("Refusing to downgrade passkey data; preserve credentials/challenges before rollback")
    op.drop_index("ix_passkey_challenges_expires_at", table_name="passkey_challenges")
    op.drop_index("ix_passkey_challenges_username", table_name="passkey_challenges")
    op.drop_table("passkey_challenges")
    op.drop_index("ix_passkey_credentials_username", table_name="passkey_credentials")
    op.drop_table("passkey_credentials")
