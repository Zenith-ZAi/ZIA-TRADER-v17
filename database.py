from sqlalchemy import Boolean, Column, DateTime, Enum, Float, Integer, JSON, String, create_engine
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone
import enum

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

class Trade(Base):
    __tablename__ = 'trades'
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
    return create_engine(database_url)

def get_session_local(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db(engine):
    Base.metadata.create_all(engine)
