from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Enum, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import enum

Base = declarative_base()

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
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    open_time = Column(DateTime, default=datetime.utcnow)
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
    start_time = Column(DateTime, default=datetime.utcnow)
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
    timestamp = Column(DateTime, default=datetime.utcnow)
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
    timestamp = Column(DateTime, default=datetime.utcnow)
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
    timestamp = Column(DateTime, default=datetime.utcnow)
    metadata_json = Column(JSON)

class WhaleActivity(Base):
    __tablename__ = 'whale_activity'
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    sentiment = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

class SystemLog(Base):
    __tablename__ = 'system_logs'
    id = Column(Integer, primary_key=True)
    level = Column(String)
    account_id = Column(String, nullable=True)
    message = Column(String)
    module = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

def get_engine(database_url: str):
    return create_engine(database_url)

def get_session_local(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db(engine):
    Base.metadata.create_all(engine)
