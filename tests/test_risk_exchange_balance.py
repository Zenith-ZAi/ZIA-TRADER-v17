from config.settings import Settings
from database_manager import DatabaseManager
from risk.risk_ai import RiskAI


def test_quote_equivalent_balance_handles_base_and_quote_assets():
    assert RiskAI.quote_equivalent_balance({"USDT": 100.0, "BTC": 0.01}, "BTC/USDT", 50000.0) == 600.0


def test_risk_ai_blocks_order_above_exchange_quote_balance(tmp_path):
    settings = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path / 'risk_exchange.db'}",
        MIN_CONFIDENCE_THRESHOLD=0.70,
        MAX_EXPOSURE_PER_SYMBOL=0.10,
        MAX_TOTAL_EXPOSURE=0.30,
    )
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    risk = RiskAI(settings, db)
    result = risk.validate_order(
        {"symbol": "BTC/USDT", "action": "buy", "price": 100.0, "confidence": 0.95},
        10000.0,
        {"exchange_balances": {"USDT": 1.0}},
    )
    assert result["valid"] is False
    assert "Saldo disponível" in result["reason"]
