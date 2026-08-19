from config.settings import Settings
from core.position_policy import evaluate_position_exit
from database import MarketType
from database_manager import DatabaseManager
from risk.risk_ai import RiskAI


def test_risk_exit_does_not_require_entry_sizing():
    db = DatabaseManager("sqlite:///:memory:")
    db.create_tables()
    settings = Settings(ALLOW_SHORT=False, DATABASE_URL="sqlite:///:memory:")
    risk = RiskAI(settings, db)
    result = risk.validate_exit(
        {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1, "exit_reason": "take_profit"},
        100.0,
        {"exchange_balances": {"BTC": 0.2, "USDT": 1000.0}},
    )
    assert result["valid"] is True
    assert result["action"] == "sell"
    assert result["quantity"] == 0.1


def test_risk_exit_blocks_missing_base_balance():
    db = DatabaseManager("sqlite:///:memory:")
    db.create_tables()
    risk = RiskAI(Settings(DATABASE_URL="sqlite:///:memory:"), db)
    result = risk.validate_exit(
        {"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1},
        100.0,
        {"exchange_balances": {"BTC": 0.01}},
    )
    assert result["valid"] is False
    assert "Saldo base" in result["reason"]


def test_position_exit_without_position_is_hold():
    result = evaluate_position_exit(None, 100.0)
    assert result["should_exit"] is False
    assert result["reason"] == "sem posição"
