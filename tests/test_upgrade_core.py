from types import SimpleNamespace

from config.settings import Settings
from core.microstructure import estimate_entry_costs
from core.multi_timeframe import combine_timeframe_signals, parse_timeframes
from core.news_gate import evaluate_news_gate
from core.risk_guard import evaluate_circuit_breaker
from core.runtime_registry import RuntimeConfigRegistry
from database import Base
from database_manager import DatabaseManager
from sqlalchemy.orm import sessionmaker
from cli.db_models import AlgorithmConfig, StrategyConfig


def signal(action, confidence=0.8):
    return SimpleNamespace(
        action=action,
        candidate_action=action,
        confidence=confidence,
        volatility=0.01,
        status="good",
    )


def test_multi_timeframe_requires_confirmation():
    assert parse_timeframes("1m, 5m, 1m,1h") == ["1m", "5m", "1h"]
    result = combine_timeframe_signals(
        {"1m": signal("buy"), "5m": signal("sell"), "1h": signal("buy")},
        "1h",
        min_confirmations=2,
    )
    assert result["confirmed"] is True
    assert result["action"] == "buy"
    assert result["confirmations"] == 2


def test_news_gate_is_fail_closed_without_context():
    settings = Settings(NEWS_FAIL_CLOSED_FOR_ENTRY=True, NEWS_MIN_HEALTHY_PROVIDERS=1, NEWS_MIN_ARTICLES_FOR_ENTRY=1)
    result = evaluate_news_gate([], {}, settings)
    assert result["entry_allowed"] is False
    assert "insuficientes" in result["reason"]


def test_news_gate_accepts_fresh_healthy_context():
    settings = Settings(NEWS_FAIL_CLOSED_FOR_ENTRY=True, NEWS_MIN_HEALTHY_PROVIDERS=1, NEWS_MIN_ARTICLES_FOR_ENTRY=1)
    result = evaluate_news_gate(
        [{"title": "Market update", "sentiment_score": 0.2, "time_published": "2026-08-20T12:00:00+00:00"}],
        {"rss": {"ok": True}},
        settings,
        now=__import__("datetime").datetime.fromisoformat("2026-08-20T12:10:00+00:00"),
    )
    assert result["entry_allowed"] is True
    assert result["fresh_articles"] == 1


def test_circuit_breaker_blocks_drawdown():
    settings = Settings(CIRCUIT_BREAKER_ENABLED=True, CIRCUIT_BREAKER_MAX_DRAWDOWN_PERCENT=0.15)
    result = evaluate_circuit_breaker(8400.0, 10000.0, 0.0, settings)
    assert result["tripped"] is True
    assert result["entry_allowed"] is False


def test_microstructure_rejects_wide_spread_and_bad_reward_risk():
    settings = Settings(
        MICROSTRUCTURE_GATE_ENABLED=True,
        MAX_SPREAD_BPS=10.0,
        MAX_ESTIMATED_SLIPPAGE_BPS=20.0,
        MIN_REWARD_RISK_RATIO=1.5,
    )
    result = estimate_entry_costs(
        {"bid": 99.0, "ask": 101.0},
        {"asks": [[101.0, 1.0]], "bids": [[99.0, 1.0]]},
        "buy",
        0.1,
        100.0,
        98.0,
        101.0,
        settings,
    )
    assert result["allowed"] is False
    assert any("spread" in reason for reason in result["reasons"])


def test_runtime_registry_applies_enabled_menu_profile(tmp_path):
    url = f"sqlite:///{tmp_path / 'registry.db'}"
    db = DatabaseManager(url)
    db.create_tables()
    session = db.SessionLocal()
    session.add(StrategyConfig(name="Menu Pullback", enabled=True, priority=10, weight=2.0, timeframes="1m,5m,1h", stop_loss=0.01, take_profit=0.03))
    session.add(AlgorithmConfig(name="Menu IA", enabled=True, weight=2.0, confluence=0.8, risk_management={"max_risk": 0.01}))
    session.commit()
    session.close()
    settings = Settings(DATABASE_URL=url, TIMEFRAME="1h", ANALYSIS_TIMEFRAMES="1h", MULTI_TIMEFRAME_ENABLED=False)
    profile = RuntimeConfigRegistry(db).apply_to_settings(settings)
    assert profile["source"] == "admin_menu"
    assert settings.TIMEFRAME == "1h"
    assert settings.ANALYSIS_TIMEFRAMES == "1m,5m,1h"
    assert settings.MULTI_TIMEFRAME_ENABLED is True
    assert settings.MAX_RISK_PER_TRADE == 0.01
    assert settings.MIN_CONFIDENCE_THRESHOLD >= 0.8


def test_forex_paper_adapter_is_deterministic_and_safe():
    import asyncio
    from execution.exchange_connector import ExchangeConnector
    from execution.forex_adapter import ForexLiveAdapter, ForexPaperAdapter, ForexAdapterError

    settings = Settings(MARKET_ADAPTER="forex", FOREX_MODE="paper", FOREX_PAPER_SPREAD=0.0002)
    connector = ExchangeConnector(settings)
    assert isinstance(connector._adapter, ForexPaperAdapter)
    asyncio.run(connector.connect())
    history = asyncio.run(connector.get_historical_data("EUR/USD", "1m", 50))
    assert len(history) == 50
    order = asyncio.run(connector.place_order("EUR/USD", "buy", "market", 1000.0))
    assert order["status"] == "success"

    live_settings = Settings(MARKET_ADAPTER="forex", FOREX_MODE="live")
    live = ExchangeConnector(live_settings)
    assert isinstance(live._adapter, ForexLiveAdapter)
    try:
        asyncio.run(live.connect())
    except ForexAdapterError:
        pass
    else:
        raise AssertionError("Forex live deveria permanecer fail-closed")
