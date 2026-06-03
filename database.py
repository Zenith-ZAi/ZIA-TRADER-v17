from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Enum as SQLEnum, JSON
from datetime import datetime
import enum
from config.settings import settings

Base = declarative_base()

class MarketType(enum.Enum):
    CRYPTO = "crypto"
    FOREX = "forex"
    INDICES = "indices"
    STOCKS = "stocks"

class TradeStatus(enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    FAILED = "failed"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    market_type = Column(SQLEnum(MarketType), default=MarketType.CRYPTO)
    action = Column(String)  # buy, sell
    quantity = Column(Float)
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    status = Column(SQLEnum(TradeStatus), default=TradeStatus.OPEN)
    execution_id = Column(String, unique=True, index=True)
    exchange = Column(String)
    strategy_used = Column(String)
    risk_score = Column(Float)
    metadata_json = Column(JSON, nullable=True) # Para auditoria detalhada
    timestamp = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

class NewsArticle(Base):
    __tablename__ = "news_articles"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    title = Column(String)
    content = Column(String)
    sentiment_score = Column(Float)
    source = Column(String)
    url = Column(String)
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class WhaleActivity(Base):
    __tablename__ = "whale_activities"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    amount = Column(Float)
    price = Column(Float)
    side = Column(String) # buy, sell
    timestamp = Column(DateTime, default=datetime.utcnow)
    metadata_json = Column(JSON, nullable=True)

class SystemLog(Base):
    __tablename__ = "system_logs"
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String)
    module = Column(String)
    message = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Database setup
async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
