from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Enum
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
    message = Column(String)
    module = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

def init_db(engine):
    Base.metadata.create_all(engine)
