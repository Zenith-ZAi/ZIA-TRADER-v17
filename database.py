from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    BigInteger,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone
import enum
import os
from uuid import uuid4

class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    """Retorna UTC sem tzinfo para compatibilidade com DateTime legado do schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

class MarketType(enum.Enum):
    CRYPTO = "crypto"
    FOREX = "forex"
    INDICES = "indices"
    STOCKS = "stocks"

class OrderStatus(enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELED = "canceled"
    REJECTED = "rejected"

class AccountState(Base):
    __tablename__ = 'account_state'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, unique=True, nullable=False)
    balance = Column(Float, default=0.0)
    initial_capital = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=utc_now, onupdate=utc_now)

class Position(Base):
    __tablename__ = 'positions'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    is_open = Column(Boolean, default=True)
    open_time = Column(DateTime, default=utc_now)
    close_time = Column(DateTime)

class RuntimePositionState(Base):
    __tablename__ = 'runtime_position_state'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    breakeven_trigger = Column(Float)
    order_id = Column(String)
    is_open = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class DailyPNL(Base):
    __tablename__ = 'daily_pnl'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)

class WeeklyPNL(Base):
    __tablename__ = 'weekly_pnl'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    week_start_date = Column(DateTime, nullable=False)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)

class MonthlyPNL(Base):
    __tablename__ = 'monthly_pnl'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    month_start_date = Column(DateTime, nullable=False)
    pnl = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)

class Drawdown(Base):
    __tablename__ = 'drawdowns'
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    start_time = Column(DateTime, default=utc_now)
    end_time = Column(DateTime)
    peak_balance = Column(Float, nullable=False)
    trough_balance = Column(Float, nullable=False)
    max_drawdown_percentage = Column(Float, nullable=False)
    drawdown = Column(Float, nullable=False, default=0.0)

class OrderHistory(Base):
    __tablename__ = 'order_history'
    __table_args__ = (Index("ix_order_history_symbol_timestamp", "symbol", "timestamp"),)
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    order_id = Column(String, unique=True, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    price = Column(Float)
    quantity = Column(Float)
    status = Column(Enum(OrderStatus), nullable=False)
    timestamp = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)

class ExecutionHistory(Base):
    __tablename__ = 'execution_history'
    __table_args__ = (Index("ix_execution_history_symbol_timestamp", "symbol", "timestamp"),)
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False)
    execution_id = Column(String, unique=True, nullable=False)
    order_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    action = Column(String, nullable=False)
    filled_price = Column(Float, nullable=False)
    filled_quantity = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)


class EquityLedgerEvent(Base):
    """Immutable, audit-only event evidence; never a risk or execution source."""
    __tablename__ = "equity_ledger_v1"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "source", "source_event_id", "line_no",
            name="uq_equity_ledger_v1_event_identity",
        ),
        CheckConstraint(
            "event_type IN ('balance_snapshot', 'trade_fill', 'fee', 'funding', 'cashflow', 'reconciliation_adjustment')",
            name="ck_equity_ledger_v1_event_type",
        ),
        CheckConstraint(
            "(event_type = 'balance_snapshot' AND amount_basis = 'balance' AND balance_component IS NOT NULL) "
            "OR (event_type <> 'balance_snapshot' AND amount_basis = 'delta' AND balance_component IS NULL AND amount <> 0)",
            name="ck_equity_ledger_v1_amount_semantics",
        ),
        CheckConstraint(
            "balance_component IS NULL OR length(trim(balance_component)) > 0",
            name="ck_equity_ledger_v1_component_nonempty",
        ),
        CheckConstraint("line_no >= 0", name="ck_equity_ledger_v1_line_no"),
        CheckConstraint(
            "length(trim(account_id)) > 0 AND length(trim(source)) > 0 "
            "AND length(trim(source_event_id)) > 0 AND length(trim(asset)) > 0",
            name="ck_equity_ledger_v1_identity_nonempty",
        ),
        CheckConstraint(
            "length(canonical_sha256) = 64",
            name="ck_equity_ledger_v1_hash_length",
        ),
        Index("ix_equity_ledger_v1_account_occurred", "account_id", "occurred_at", "id"),
    )
    id = Column(Integer, primary_key=True)
    account_id = Column(String(128), nullable=False)
    source = Column(String(64), nullable=False)
    source_event_id = Column(String(160), nullable=False)
    line_no = Column(Integer, nullable=False, default=0)
    event_type = Column(String(32), nullable=False)
    asset = Column(String(32), nullable=False)
    amount = Column(Numeric(38, 18), nullable=False)
    amount_basis = Column(String(8), nullable=False)
    balance_component = Column(String(16))
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    reference_type = Column(String(32))
    reference_id = Column(String(160))
    canonical_sha256 = Column(String(64), nullable=False)


class Trade(Base):
    __tablename__ = 'trades'
    __table_args__ = (Index("ix_trades_symbol_timestamp", "symbol", "timestamp"),)
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    market_type = Column(Enum(MarketType), nullable=False)
    action = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    confidence = Column(Float)
    timestamp = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)

class WhaleActivity(Base):
    __tablename__ = 'whale_activity'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    sentiment = Column(String)
    timestamp = Column(DateTime, default=utc_now)

class NewsArticle(Base):
    __tablename__ = 'news_articles'
    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False)
    symbol = Column(String, nullable=True)
    title = Column(String, nullable=False)
    summary = Column(String)
    url = Column(String)
    published_at = Column(DateTime)
    sentiment_score = Column(Float, default=0.0)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now)


class TrendSnapshot(Base):
    __tablename__ = 'trend_snapshots'
    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    trend_score = Column(Float, default=0.0)
    market_cap_rank = Column(Integer)
    price_change_24h = Column(Float)
    observed_at = Column(DateTime, default=utc_now)
    metadata_json = Column(JSON)


class AIObservation(Base):
    __tablename__ = 'ai_observations'
    __table_args__ = (Index("ix_ai_observations_symbol_observed_at", "symbol", "observed_at"),)
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    observed_at = Column(DateTime, default=utc_now, index=True)
    mode = Column(String, nullable=False, default="shadow")
    action = Column(String, nullable=False, default="hold")
    candidate_action = Column(String, nullable=False, default="hold")
    confidence = Column(Float, default=0.0)
    model_action = Column(String, nullable=False, default="hold")
    model_confidence = Column(Float, default=0.0)
    market_signal_action = Column(String, nullable=False, default="hold")
    market_signal_confidence = Column(Float, default=0.0)
    price = Column(Float, default=0.0)
    news_sentiment = Column(Float, default=0.0)
    trend_score = Column(Float, default=0.0)
    event_blocked = Column(Boolean, default=False)
    risk_valid = Column(Boolean, default=False)
    decision_latency_ms = Column(Float, default=0.0)
    news_latency_ms = Column(Float, default=0.0)
    forward_return = Column(Float, nullable=True)
    outcome_label = Column(Integer, nullable=True)
    metadata_json = Column(JSON)


class MarketPattern(Base):
    __tablename__ = 'market_patterns'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    strategy = Column(String, nullable=False, default="pullback")
    observed_at = Column(DateTime, default=utc_now, index=True)
    pattern_type = Column(String, nullable=False, default="pullback")
    signature_json = Column(JSON, nullable=False, default=dict)
    entry_price = Column(Float, default=0.0)
    atr = Column(Float, default=0.0)
    outcome_atr = Column(Float, nullable=True)
    outcome_label = Column(Integer, nullable=True)
    sample_size = Column(Integer, default=1)
    source_observation_id = Column(Integer, nullable=True)
    metadata_json = Column(JSON)


class SystemLog(Base):
    __tablename__ = 'system_logs'
    id = Column(Integer, primary_key=True)
    level = Column(String)
    account_id = Column(String, nullable=True)
    message = Column(String)
    module = Column(String)
    timestamp = Column(DateTime, default=utc_now)

def get_engine(database_url: str):
    engine = create_engine(database_url)
    configure_sqlite_engine(engine)
    return engine

def get_session_local(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db(engine):
    if engine.dialect.name == "sqlite":
        if os.getenv("ENVIRONMENT", "development").strip().lower() in {"prod", "production"}:
            raise RuntimeError("SQLite/create_all não é permitido em produção; configure PostgreSQL e execute Alembic")
        configure_sqlite_engine(engine)
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.exec_driver_sql("PRAGMA recursive_triggers = ON")
        Base.metadata.create_all(engine)
        install_sqlite_append_only_guards(engine)
        return
    if engine.dialect.name != "postgresql":
        raise RuntimeError(f"Dialeto de banco não suportado para migrações: {engine.dialect.name}")
    from infra.db_migrations import upgrade_database

    upgrade_database(engine)


_SQLITE_APPEND_ONLY_TABLES = (
    "equity_ledger_v1",
    "ledger_scope_v1",
    "ledger_coverage_manifest_v1",
    "ledger_balance_snapshot_v1",
    "ledger_fact_v1",
    "ledger_period_closure_v1",
)


def configure_sqlite_engine(engine):
    """Enable SQLite FK and recursive-trigger enforcement on every pooled connection."""
    if engine.dialect.name != "sqlite":
        return
    if not getattr(engine, "_zia_sqlite_integrity_configured", False):
        def _enable_sqlite_integrity(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA recursive_triggers = ON")
            finally:
                cursor.close()

        event.listen(engine, "connect", _enable_sqlite_integrity)
        engine._zia_sqlite_integrity_configured = True


def install_sqlite_append_only_guards(engine):
    """Install development/test SQLite guards for every ledger evidence table present."""
    if engine.dialect.name != "sqlite":
        return
    existing_tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        for table in _SQLITE_APPEND_ONLY_TABLES:
            if table not in existing_tables:
                continue
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
                f"BEFORE UPDATE ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'ledger evidence is append-only'); END"
            )
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
                f"BEFORE DELETE ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'ledger evidence is append-only'); END"
            )


class OrderIntent(Base):
    """Intenção local idempotente antes e durante o envio à exchange."""
    __tablename__ = "order_intents"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    client_order_id = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False, default="market")
    quantity = Column(Float, nullable=False)
    price = Column(Float)
    status = Column(String, nullable=False, default="reserved")
    exchange_order_id = Column(String)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String)
    payload_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class ReconciliationSnapshot(Base):
    __tablename__ = "reconciliation_snapshots"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    open_orders_count = Column(Integer, default=0)
    positions_count = Column(Integer, default=0)
    payload_json = Column(JSON)
    observed_at = Column(DateTime, default=utc_now, index=True)


class ProtectionOrder(Base):
    __tablename__ = "protection_orders"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    parent_client_order_id = Column(String, nullable=False, index=True)
    client_order_id = Column(String, unique=True, nullable=False)
    exchange_order_id = Column(String)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    stop_price = Column(Float)
    limit_price = Column(Float)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KillSwitchEvent(Base):
    __tablename__ = "kill_switch_events"
    id = Column(Integer, primary_key=True)
    account_id = Column(String, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    reason = Column(String, nullable=False)
    actor = Column(String, nullable=False, default="system")
    created_at = Column(DateTime, default=utc_now, index=True)


class BacktestRun(Base):
    """Registro auditável de uma execução histórica, sem promover modelos automaticamente."""
    __tablename__ = "backtest_runs"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, default="1h")
    mode = Column(String, nullable=False, default="historical")
    dataset_path = Column(String, nullable=False)
    dataset_sha256 = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="completed")
    initial_capital = Column(Float)
    final_capital = Column(Float)
    total_pnl = Column(Float)
    return_pct = Column(Float)
    sharpe_ratio = Column(Float)
    maximum_drawdown = Column(Float)
    trades_executed = Column(Integer, default=0)
    configuration_json = Column(JSON)
    result_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now, index=True)


class DecisionSnapshot(Base):
    """Contexto imutável de uma decisão para paridade live, shadow e replay."""
    __tablename__ = "decision_snapshots"
    __table_args__ = (Index("ix_decision_snapshots_symbol_timeframe_observed_at", "symbol", "timeframe", "observed_at"),)
    id = Column(Integer, primary_key=True)
    snapshot_id = Column(String, unique=True, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, default="1h")
    mode = Column(String, nullable=False, default="shadow")
    observed_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    dataset_path = Column(String)
    dataset_sha256 = Column(String)
    feature_hash = Column(String)
    action = Column(String, nullable=False, default="hold")
    candidate_action = Column(String, nullable=False, default="hold")
    confidence = Column(Float, default=0.0)
    gate_status = Column(String, nullable=False, default="blocked")
    before_context_json = Column(JSON, nullable=False, default=dict)
    after_context_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now, index=True)


class MarketCandle(Base):
    """OHLCV keyed by provider and market identity; reimports are idempotent."""
    __tablename__ = "market_candles"
    __table_args__ = (
        Index("ix_market_candles_symbol_timeframe_timestamp", "symbol", "timeframe", "timestamp"),
    )
    symbol = Column(String(64), primary_key=True, nullable=False)
    timeframe = Column(String(16), primary_key=True, nullable=False)
    timestamp = Column(DateTime, primary_key=True, nullable=False)
    source = Column(String(64), primary_key=True, nullable=False, default="unknown")
    asset_class = Column(String(16), primary_key=True, nullable=False, default="unknown", server_default="unknown")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    volume_status = Column(String(24), nullable=False, default="reported", server_default="reported")
    created_at = Column(DateTime, nullable=False, default=utc_now)


class ModelRegistry(Base):
    """Metadados auditáveis de artefatos; não promove modelos nem altera o gate hold."""
    __tablename__ = "model_registry"
    id = Column(Integer, primary_key=True)
    model_name = Column(String(128), nullable=False)
    version = Column(String(128), nullable=False, unique=True)
    artifact_sha256 = Column(String(64), nullable=False)
    dataset_sha256 = Column(String(64))
    metrics_oos_json = Column(JSON, nullable=False, default=dict)
    training_config_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="candidate")
    registered_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    __table_args__ = (Index("ix_model_registry_name_status", "model_name", "status"),)


class ModelMetric(Base):
    """Métricas versionadas por split/regime para acompanhar avaliação fora da amostra."""
    __tablename__ = "model_metrics"
    id = Column(Integer, primary_key=True)
    model_version = Column(String(128), ForeignKey("model_registry.version", ondelete="RESTRICT"), nullable=False)
    metric_name = Column(String(64), nullable=False)
    regime = Column(String(64), nullable=False, default="all")
    split = Column(String(32), nullable=False, default="oos")
    metric_value = Column(Float, nullable=False)
    measured_at = Column(DateTime, nullable=False, default=utc_now)
    __table_args__ = (Index("ix_model_metrics_version_regime_time", "model_version", "regime", "measured_at"),)


class DataGap(Base):
    """Gap/staleness de feed registrado sem autorizar sinais com dados inválidos."""
    __tablename__ = "data_gaps"
    id = Column(Integer, primary_key=True)
    source = Column(String(64), nullable=False)
    symbol = Column(String(64), nullable=False)
    timeframe = Column(String(16), nullable=False)
    gap_start = Column(DateTime, nullable=False)
    gap_end = Column(DateTime)
    detected_at = Column(DateTime, nullable=False, default=utc_now)
    status = Column(String(32), nullable=False, default="open")
    details_json = Column(JSON, nullable=False, default=dict)
    __table_args__ = (Index("ix_data_gaps_symbol_timeframe_detected_at", "symbol", "timeframe", "detected_at"),)


class OrderBookSnapshot(Base):
    """Snapshot bruto de depth para auditoria; não participa de execução de ordens."""
    __tablename__ = "order_book_snapshots"
    id = Column(Integer, primary_key=True)
    source = Column(String(64), nullable=False)
    symbol = Column(String(64), nullable=False)
    observed_at = Column(DateTime, nullable=False, index=True)
    bids_json = Column(JSON, nullable=False, default=list)
    asks_json = Column(JSON, nullable=False, default=list)
    last_update_id = Column(String(128))
    created_at = Column(DateTime, nullable=False, default=utc_now)
    __table_args__ = (Index("ix_order_book_snapshots_symbol_observed_at", "symbol", "observed_at"),)


class AdminAuditLog(Base):
    """Registro aditivo de ações administrativas; não guarda segredos ou credenciais."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    actor = Column(String(128), nullable=False)
    action = Column(String(128), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(128))
    correlation_id = Column(String(128))
    details_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    __table_args__ = (Index("ix_audit_log_actor_created_at", "actor", "created_at"),)


class TenantV1(Base):
    """Tenant identity for the additive client-scope foundation.

    The identifier is deliberately stored as a canonical UUID string so the
    same metadata and migration work on SQLite and PostgreSQL.  This table is
    identity metadata only; it is not an authorization policy or an order
    permission grant.
    """

    __tablename__ = "tenant_v1"
    __table_args__ = (
        CheckConstraint(
            "length(id) = 36 AND lower(id) = id "
            "AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-' "
            "AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'",
            name="ck_tenant_v1_id_canonical_uuid",
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_tenant_v1_name_nonempty"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_tenant_v1_status"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    name = Column(String(128), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class PrincipalV1(Base):
    """Persisted issuer/subject identity; it intentionally has no password."""

    __tablename__ = "principal_v1"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_principal_v1_issuer_subject"),
        CheckConstraint(
            "length(id) = 36 AND lower(id) = id "
            "AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-' "
            "AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'",
            name="ck_principal_v1_id_canonical_uuid",
        ),
        CheckConstraint(
            "length(trim(issuer)) > 0 AND length(trim(subject)) > 0",
            name="ck_principal_v1_identity_nonempty",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_principal_v1_status"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    issuer = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    status = Column(String(16), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class TenantMembershipV1(Base):
    """Active membership connecting one persisted principal to one tenant."""

    __tablename__ = "tenant_membership_v1"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'trader', 'admin')", name="ck_tenant_membership_v1_role"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_tenant_membership_v1_status"),
    )

    tenant_id = Column(
        String(36),
        ForeignKey("tenant_v1.id", name="fk_tenant_membership_v1_tenant", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    )
    principal_id = Column(
        String(36),
        ForeignKey("principal_v1.id", name="fk_tenant_membership_v1_principal", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    )
    role = Column(String(16), nullable=False, default="viewer", server_default="viewer")
    status = Column(String(16), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class BrokerAccountV1(Base):
    """Opaque broker account reference owned by exactly one tenant.

    ``account_ref`` is an application-level opaque identifier only.  No API
    key, secret, token, passphrase, or other credential belongs in this table.
    """

    __tablename__ = "broker_account_v1"
    __table_args__ = (
        UniqueConstraint(
            "venue",
            "environment",
            "account_ref",
            name="uq_broker_account_v1_venue_environment_ref",
        ),
        CheckConstraint(
            "length(id) = 36 AND lower(id) = id "
            "AND substr(id, 9, 1) = '-' AND substr(id, 14, 1) = '-' "
            "AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'",
            name="ck_broker_account_v1_id_canonical_uuid",
        ),
        CheckConstraint(
            "length(trim(venue)) > 0 AND length(trim(environment)) > 0 "
            "AND length(trim(account_ref)) > 0",
            name="ck_broker_account_v1_identity_nonempty",
        ),
        CheckConstraint(
            "environment IN ('paper', 'testnet', 'demo', 'live')",
            name="ck_broker_account_v1_environment",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_broker_account_v1_status"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    tenant_id = Column(
        String(36),
        ForeignKey("tenant_v1.id", name="fk_broker_account_v1_tenant", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    venue = Column(String(64), nullable=False)
    environment = Column(String(16), nullable=False)
    account_ref = Column(String(255), nullable=False)
    status = Column(String(16), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class LedgerScopeV1(Base):
    """Escopo financeiro separado por conta persistida; não atesta autenticidade."""

    __tablename__ = "ledger_scope_v1"
    __table_args__ = (
        UniqueConstraint("broker_account_id", name="uq_ledger_scope_v1_broker_account"),
        CheckConstraint(
            "length(id) = 36 AND lower(id) = id AND substr(id, 9, 1) = '-' "
            "AND substr(id, 14, 1) = '-' AND substr(id, 19, 1) = '-' AND substr(id, 24, 1) = '-'",
            name="ck_ledger_scope_v1_id_uuid",
        ),
        CheckConstraint("length(trim(base_asset)) > 0", name="ck_ledger_scope_v1_base_asset"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    broker_account_id = Column(
        String(36),
        ForeignKey("broker_account_v1.id", name="fk_ledger_scope_v1_broker_account", ondelete="RESTRICT"),
        nullable=False,
    )
    base_asset = Column(String(32), nullable=False)
    created_at_utc = Column(DateTime(timezone=True), nullable=False)


class LedgerCoverageManifestV1(Base):
    """Manifesto append-only de cobertura; complete não é autoautorização."""

    __tablename__ = "ledger_coverage_manifest_v1"
    __table_args__ = (
        UniqueConstraint("scope_id", "manifest_id", name="uq_ledger_coverage_manifest_scope_id"),
        CheckConstraint("length(trim(endpoint)) > 0", name="ck_ledger_coverage_endpoint"),
        CheckConstraint(
            "reconciliation_status IN ('pending', 'attention')",
            name="ck_ledger_coverage_reconciliation_status",
        ),
        CheckConstraint(
            "coverage_start_utc < coverage_end_utc",
            name="ck_ledger_coverage_interval",
        ),
        CheckConstraint(
            "complete = false",
            name="ck_ledger_coverage_not_verified_in_foundation",
        ),
    )

    manifest_id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    scope_id = Column(
        String(36),
        ForeignKey("ledger_scope_v1.id", name="fk_ledger_coverage_scope", ondelete="RESTRICT"),
        nullable=False,
    )
    endpoint = Column(String(128), nullable=False)
    requested_at_utc = Column(DateTime(timezone=True), nullable=False)
    received_at_utc = Column(DateTime(timezone=True), nullable=False)
    cursor_start = Column(String(255))
    cursor_end = Column(String(255))
    coverage_start_utc = Column(DateTime(timezone=True), nullable=False)
    coverage_end_utc = Column(DateTime(timezone=True), nullable=False)
    expected_assets_json = Column(JSON, nullable=False)
    complete = Column(Boolean, nullable=False, default=False, server_default="false")
    reconciliation_status = Column(String(16), nullable=False, default="pending", server_default="pending")


class LedgerBalanceSnapshotV1(Base):
    """Saldo observado por ativo, ligado a um manifesto de cobertura persistido."""

    __tablename__ = "ledger_balance_snapshot_v1"
    __table_args__ = (
        UniqueConstraint(
            "scope_id", "snapshot_id", "asset", name="uq_ledger_balance_scope_snapshot_asset"
        ),
        ForeignKeyConstraint(
            ["scope_id", "coverage_manifest_id"],
            ["ledger_coverage_manifest_v1.scope_id", "ledger_coverage_manifest_v1.manifest_id"],
            name="fk_ledger_balance_coverage_manifest",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(asset)) > 0", name="ck_ledger_balance_asset"),
        CheckConstraint(
            "free_amount >= 0 AND locked_amount >= 0 AND total_amount >= 0",
            name="ck_ledger_balance_nonnegative",
        ),
        CheckConstraint("length(trim(source_cursor)) > 0", name="ck_ledger_balance_cursor"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    scope_id = Column(String(36), nullable=False)
    snapshot_id = Column(String(36), nullable=False)
    asset = Column(String(32), nullable=False)
    free_amount = Column(Numeric(38, 18), nullable=False)
    locked_amount = Column(Numeric(38, 18), nullable=False)
    total_amount = Column(Numeric(38, 18), nullable=False)
    as_of_utc = Column(DateTime(timezone=True), nullable=False)
    ingested_at_utc = Column(DateTime(timezone=True), nullable=False)
    source_cursor = Column(String(255), nullable=False)
    coverage_manifest_id = Column(String(36), nullable=False)


class LedgerFactV1(Base):
    """Fato financeiro append-only; preenchimento não significa verificação."""

    __tablename__ = "ledger_fact_v1"
    __table_args__ = (
        UniqueConstraint(
            "scope_id", "fact_type", "source_event_id", "source_line_no",
            name="uq_ledger_fact_scope_event_line",
        ),
        CheckConstraint(
            "fact_type IN ('fill', 'fee', 'funding', 'cashflow')",
            name="ck_ledger_fact_type",
        ),
        CheckConstraint(
            "length(trim(source_event_id)) > 0 AND length(trim(asset)) > 0 "
            "AND length(trim(adapter_name)) > 0 AND length(trim(adapter_version)) > 0",
            name="ck_ledger_fact_identity_nonempty",
        ),
        CheckConstraint("source_line_no >= 0", name="ck_ledger_fact_line_no"),
        CheckConstraint("amount <> 0", name="ck_ledger_fact_nonzero_amount"),
        CheckConstraint(
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
        CheckConstraint(
            "raw_evidence_sha256 IS NULL OR length(raw_evidence_sha256) = 64",
            name="ck_ledger_fact_raw_digest_length",
        ),
        Index("ix_ledger_fact_scope_occurred", "scope_id", "occurred_at_utc", "id"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    scope_id = Column(
        String(36),
        ForeignKey("ledger_scope_v1.id", name="fk_ledger_fact_scope", ondelete="RESTRICT"),
        nullable=False,
    )
    fact_type = Column(String(16), nullable=False)
    source_event_id = Column(String(255), nullable=False)
    source_line_no = Column(Integer, nullable=False, default=0, server_default="0")
    source_sequence = Column(BigInteger)
    asset = Column(String(32), nullable=False)
    amount = Column(Numeric(38, 18), nullable=False)
    occurred_at_utc = Column(DateTime(timezone=True), nullable=False)
    ingested_at_utc = Column(DateTime(timezone=True), nullable=False)
    client_order_id = Column(String(160))
    venue_order_id = Column(String(160))
    venue_trade_id = Column(String(160))
    symbol = Column(String(64))
    side = Column(String(8))
    quantity = Column(Numeric(38, 18))
    price = Column(Numeric(38, 18))
    fee_asset = Column(String(32))
    fee_amount = Column(Numeric(38, 18))
    funding_period_start_utc = Column(DateTime(timezone=True))
    funding_period_end_utc = Column(DateTime(timezone=True))
    funding_rate = Column(Numeric(38, 18))
    cashflow_kind = Column(String(16))
    external_reference = Column(String(255))
    adapter_name = Column(String(64), nullable=False)
    adapter_version = Column(String(64), nullable=False)
    raw_evidence_ref = Column(String(512))
    raw_evidence_sha256 = Column(String(64))


class LedgerPeriodClosureV1(Base):
    """Tentativa imutável de fechamento; somente reconciliador futuro poderá produzi-la."""

    __tablename__ = "ledger_period_closure_v1"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scope_id", "opening_manifest_id"],
            ["ledger_coverage_manifest_v1.scope_id", "ledger_coverage_manifest_v1.manifest_id"],
            name="fk_ledger_closure_opening_manifest",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scope_id", "closing_manifest_id"],
            ["ledger_coverage_manifest_v1.scope_id", "ledger_coverage_manifest_v1.manifest_id"],
            name="fk_ledger_closure_closing_manifest",
            ondelete="RESTRICT",
        ),
        CheckConstraint("period_start_utc < period_end_utc", name="ck_ledger_closure_period"),
        CheckConstraint("fact_count >= 0 AND missing_count >= 0 AND late_count >= 0", name="ck_ledger_closure_counts"),
        CheckConstraint(
            "status IN ('open', 'attention')",
            name="ck_ledger_closure_not_verified_in_foundation",
        ),
        CheckConstraint(
            "closed_at_utc IS NULL",
            name="ck_ledger_closure_no_verified_timestamp_in_foundation",
        ),
        Index("ix_ledger_closure_scope_period", "scope_id", "period_start_utc", "period_end_utc"),
    )

    id = Column(String(36), primary_key=True, nullable=False, default=lambda: str(uuid4()))
    scope_id = Column(String(36), nullable=False)
    period_start_utc = Column(DateTime(timezone=True), nullable=False)
    period_end_utc = Column(DateTime(timezone=True), nullable=False)
    opening_manifest_id = Column(String(36), nullable=False)
    closing_manifest_id = Column(String(36), nullable=False)
    fact_watermark_utc = Column(DateTime(timezone=True), nullable=False)
    fact_count = Column(Integer, nullable=False)
    missing_count = Column(Integer, nullable=False)
    late_count = Column(Integer, nullable=False)
    fees_included = Column(Boolean, nullable=False)
    funding_included = Column(Boolean, nullable=False)
    cashflows_reconciled = Column(Boolean, nullable=False)
    balances_reconciled = Column(Boolean, nullable=False)
    status = Column(String(16), nullable=False)
    recorded_at_utc = Column(DateTime(timezone=True), nullable=False)
    closed_at_utc = Column(DateTime(timezone=True))
