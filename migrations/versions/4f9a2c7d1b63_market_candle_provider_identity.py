"""preserve market candle provider and asset-class identity

Revision ID: 4f9a2c7d1b63
Revises: b7d2d043ee8a
Create Date: 2026-11-03 15:13:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f9a2c7d1b63"
down_revision: Union[str, None] = "b7d2d043ee8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "market_candles"
NEW_PK = ["source", "asset_class", "symbol", "timeframe", "timestamp"]
OLD_PK = ["symbol", "timeframe", "timestamp"]


def _current_pk(bind) -> tuple[str | None, set[str]]:
    constraint = sa.inspect(bind).get_pk_constraint(TABLE)
    return constraint.get("name"), set(constraint.get("constrained_columns") or [])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    pk_name, pk_columns = _current_pk(bind)

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            TABLE,
            recreate="always",
            naming_convention={"pk": "pk_%(table_name)s"},
        ) as batch_op:
            if "asset_class" not in columns:
                batch_op.add_column(
                    sa.Column("asset_class", sa.String(length=16), nullable=False, server_default="unknown")
                )
            if "volume_status" not in columns:
                batch_op.add_column(
                    sa.Column("volume_status", sa.String(length=24), nullable=False, server_default="reported")
                )
            if pk_columns != set(NEW_PK):
                batch_op.drop_constraint(pk_name or "pk_market_candles", type_="primary")
                batch_op.create_primary_key("pk_market_candles", NEW_PK)
        return

    if "asset_class" not in columns:
        op.add_column(
            TABLE,
            sa.Column("asset_class", sa.String(length=16), nullable=False, server_default="unknown"),
        )
    if "volume_status" not in columns:
        op.add_column(
            TABLE,
            sa.Column("volume_status", sa.String(length=24), nullable=False, server_default="reported"),
        )
    if pk_columns != set(NEW_PK):
        if pk_name:
            op.drop_constraint(pk_name, TABLE, type_="primary")
        op.create_primary_key("pk_market_candles", TABLE, NEW_PK)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        return

    duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM market_candles "
            "GROUP BY symbol, timeframe, timestamp HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Downgrade blocked: candles from multiple providers share a timestamp; "
            "dropping provider identity would lose data."
        )

    pk_name, pk_columns = _current_pk(bind)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            TABLE,
            recreate="always",
            naming_convention={"pk": "pk_%(table_name)s"},
        ) as batch_op:
            if pk_columns != set(OLD_PK):
                batch_op.drop_constraint(pk_name or "pk_market_candles", type_="primary")
                batch_op.create_primary_key("pk_market_candles", OLD_PK)
            batch_op.drop_column("volume_status")
            batch_op.drop_column("asset_class")
        return

    if pk_columns != set(OLD_PK):
        if pk_name:
            op.drop_constraint(pk_name, TABLE, type_="primary")
        op.create_primary_key("pk_market_candles", TABLE, OLD_PK)
    op.drop_column(TABLE, "volume_status")
    op.drop_column(TABLE, "asset_class")
