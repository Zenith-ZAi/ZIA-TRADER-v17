import logging
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    action = Column(String)
    quantity = Column(Float)
    price = Column(Float)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    pnl = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="open")
    order_id = Column(String, unique=True, nullable=True, index=True)
    exit_price = Column(Float, nullable=True)
    exit_time = Column(DateTime, nullable=True)


class NewsArticle(Base):
    __tablename__ = "news_articles"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    title = Column(String)
    content = Column(String, nullable=True)
    sentiment_score = Column(Float, nullable=True)
    source = Column(String, nullable=True)
    url = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)


# Build the engine — SQLite needs special connect_args for async
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=_connect_args,
)

AsyncSessionLocal = sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Create all tables if they don't exist yet."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def save_trade(trade_data: dict) -> None:
    """Persist a trade record to the database."""
    async with AsyncSessionLocal() as session:
        trade = Trade(
            symbol=trade_data.get("symbol"),
            action=trade_data.get("action"),
            quantity=trade_data.get("quantity", 0.0),
            price=trade_data.get("price", 0.0),
            stop_loss=trade_data.get("stop_loss"),
            take_profit=trade_data.get("take_profit"),
            pnl=trade_data.get("pnl", 0.0),
            status=trade_data.get("status", "open"),
            order_id=trade_data.get("order_id"),
        )
        session.add(trade)
        await session.commit()
        logger.info(f"Trade persisted: {trade_data.get('order_id')}")


async def close_trade_in_db(order_id: str, exit_price: float, pnl: float) -> None:
    """Update a trade record when the position is closed."""
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select, update

        stmt = (
            update(Trade)
            .where(Trade.order_id == order_id)
            .values(
                status="closed",
                exit_price=exit_price,
                exit_time=datetime.utcnow(),
                pnl=pnl,
            )
        )
        await session.execute(stmt)
        await session.commit()
        logger.info(f"Trade closed in DB: {order_id} | PnL: {pnl:.2f}")
