"""
Additional SQLAlchemy models used exclusively by the Admin CLI.
These tables are created alongside the core tables.
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, JSON, Text
)
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

# Re-use the same Base so create_all() covers both sets of tables
from database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    id              = Column(Integer, primary_key=True)
    username        = Column(String(64), unique=True, nullable=False)
    password_hash   = Column(String(256), nullable=False)
    role            = Column(String(32), default="operator")   # admin | operator | reader | guest
    is_blocked      = Column(Boolean, default=False)
    must_change_pwd = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)
    last_login      = Column(DateTime)
    failed_attempts = Column(Integer, default=0)


class ExchangeConfig(Base):
    __tablename__ = "exchange_configs"
    id                     = Column(Integer, primary_key=True)
    name                   = Column(String(64), nullable=False)       # binance, bybit …
    api_key_encrypted      = Column(Text, default="")
    secret_key_encrypted   = Column(Text, default="")
    passphrase_encrypted   = Column(Text, default="")
    account_name           = Column(String(128), default="")
    description            = Column(Text, default="")
    testnet                = Column(Boolean, default=True)
    is_active              = Column(Boolean, default=True)
    created_at             = Column(DateTime, default=datetime.utcnow)


class StrategyConfig(Base):
    __tablename__ = "strategy_configs"
    id          = Column(Integer, primary_key=True)
    name        = Column(String(64), unique=True, nullable=False)
    enabled     = Column(Boolean, default=False)
    priority    = Column(Integer, default=5)
    weight      = Column(Float, default=1.0)
    timeframes  = Column(String(128), default="1h")
    stop_loss   = Column(Float, default=0.02)
    take_profit = Column(Float, default=0.04)
    trailing    = Column(Boolean, default=False)
    params_json = Column(JSON, default=dict)


class AlgorithmConfig(Base):
    __tablename__ = "algorithm_configs"
    id               = Column(Integer, primary_key=True)
    name             = Column(String(64), unique=True, nullable=False)
    description      = Column(Text, default="")
    indicators       = Column(JSON, default=list)
    weight           = Column(Float, default=1.0)
    confluence       = Column(Float, default=0.7)
    risk_management  = Column(JSON, default=dict)
    score            = Column(Float, default=0.0)
    enabled          = Column(Boolean, default=True)
