from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from database import Base
from database_manager import DatabaseManager
import cli.db_models  # noqa: F401 — inclui as tabelas administrativas no metadata


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def _config() -> Config:
    return Config(os.path.join(PROJECT_ROOT, "alembic.ini"))


def _exercise_migrations(database_url: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = _config()

    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # segunda execução precisa ser no-op
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
        assert "ix_decision_snapshots_symbol_timeframe_observed_at" in {
            index["name"] for index in inspector.get_indexes("decision_snapshots")
        }
        assert {"symbol", "timeframe", "timestamp"} == set(
            inspector.get_pk_constraint("market_candles")["constrained_columns"]
        )
        candle = (
            "INSERT INTO market_candles "
            "(symbol, timeframe, timestamp, open, high, low, close, volume, source, created_at) "
            "VALUES ('BTC/USDT', '1h', '2026-01-01 00:00:00', 1, 2, 0.5, 1.5, 10, 'test', '2026-01-01 00:00:00')"
        )
        with engine.begin() as connection:
            connection.execute(text(candle))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(candle))

        # Autogenerate não deve encontrar divergência entre metadata e schema migrado.
        command.check(cfg)
        command.downgrade(cfg, "base")
        assert not (set(inspect(engine).get_table_names()) - {"sqlite_sequence", "alembic_version"})
        command.upgrade(cfg, "head")
        assert set(Base.metadata.tables).issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()


def test_initial_migration_upgrade_downgrade_upgrade_sqlite(tmp_path, monkeypatch):
    _exercise_migrations(f"sqlite:///{tmp_path / 'migration.db'}", monkeypatch)


def test_database_manager_pool_configuration_and_production_sqlite_guard(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "7")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "12")
    pg = DatabaseManager("postgresql+psycopg2://user:password@localhost/zia_test")
    try:
        assert pg.engine.pool.size() == 7
        assert pg.engine.pool._max_overflow == 3
        assert pg.engine.pool._timeout == 12
    finally:
        pg.engine.dispose()

    monkeypatch.setenv("ENVIRONMENT", "production")
    sqlite = DatabaseManager("sqlite:///:memory:")
    try:
        with pytest.raises(RuntimeError, match="SQLite/create_all não é permitido em produção"):
            sqlite.create_tables()
    finally:
        sqlite.engine.dispose()


def test_initial_migration_adopts_legacy_create_all_schema(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy_engine = create_engine(database_url)
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        for table_name in ("model_metrics", "model_registry", "data_gaps", "audit_log", "market_candles"):
            connection.execute(text(f'DROP TABLE "{table_name}"'))
        for index_name in (
            "ix_order_history_symbol_timestamp",
            "ix_execution_history_symbol_timestamp",
            "ix_trades_symbol_timestamp",
            "ix_ai_observations_symbol_observed_at",
            "ix_decision_snapshots_symbol_timeframe_observed_at",
        ):
            connection.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
    legacy_engine.dispose()

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    command.upgrade(_config(), "head")
    migrated_engine = create_engine(database_url)
    try:
        assert set(Base.metadata.tables).issubset(set(inspect(migrated_engine).get_table_names()))
        for index_name, table_name in (
            ("ix_order_history_symbol_timestamp", "order_history"),
            ("ix_execution_history_symbol_timestamp", "execution_history"),
            ("ix_trades_symbol_timestamp", "trades"),
            ("ix_ai_observations_symbol_observed_at", "ai_observations"),
            ("ix_decision_snapshots_symbol_timeframe_observed_at", "decision_snapshots"),
        ):
            assert index_name in {item["name"] for item in inspect(migrated_engine).get_indexes(table_name)}
    finally:
        migrated_engine.dispose()


def test_initial_migration_upgrade_downgrade_upgrade_postgresql(monkeypatch):
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL não configurada; PostgreSQL validado no serviço de CI")
    _exercise_migrations(database_url, monkeypatch)
