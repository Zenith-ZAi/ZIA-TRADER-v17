"""add bounded order-book history

Revision ID: b7d2d043ee8a
Revises: 8d429f0ec081
Create Date: 2026-10-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d2d043ee8a"
down_revision: Union[str, None] = "8d429f0ec081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name) and any(
        item.get("name") == index_name for item in inspector.get_indexes(table_name)
    )


def upgrade() -> None:
    if not _table_exists("order_book_snapshots"):
        op.create_table(
            "order_book_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("symbol", sa.String(length=64), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("bids_json", sa.JSON(), nullable=False),
            sa.Column("asks_json", sa.JSON(), nullable=False),
            sa.Column("last_update_id", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("order_book_snapshots", "ix_order_book_snapshots_observed_at"):
        op.create_index(
            "ix_order_book_snapshots_observed_at",
            "order_book_snapshots",
            ["observed_at"],
            unique=False,
        )
    if not _index_exists("order_book_snapshots", "ix_order_book_snapshots_symbol_observed_at"):
        op.create_index(
            "ix_order_book_snapshots_symbol_observed_at",
            "order_book_snapshots",
            ["symbol", "observed_at"],
            unique=False,
        )


def downgrade() -> None:
    if _table_exists("order_book_snapshots"):
        if _index_exists("order_book_snapshots", "ix_order_book_snapshots_symbol_observed_at"):
            op.drop_index("ix_order_book_snapshots_symbol_observed_at", table_name="order_book_snapshots")
        if _index_exists("order_book_snapshots", "ix_order_book_snapshots_observed_at"):
            op.drop_index("ix_order_book_snapshots_observed_at", table_name="order_book_snapshots")
        op.drop_table("order_book_snapshots")
