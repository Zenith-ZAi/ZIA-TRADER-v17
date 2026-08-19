from database import AIObservation
from database_manager import DatabaseManager


def test_ai_shadow_observation_is_persisted(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'ai.db'}")
    manager.create_tables()
    manager.create_ai_observation({
        "symbol": "BTC/USDT",
        "mode": "shadow",
        "action": "hold",
        "candidate_action": "buy",
        "confidence": 0.61,
        "model_action": "hold",
        "model_confidence": 0.50,
        "market_signal_action": "hold",
        "market_signal_confidence": 0.61,
        "price": 100.0,
        "news_sentiment": 0.2,
        "trend_score": 0.4,
        "event_blocked": False,
        "risk_valid": False,
        "metadata_json": {"features": {"rsi_norm": 0.1}},
    })
    records = manager.get_ai_observations("BTC/USDT")
    assert len(records) == 1
    assert records[0].mode == "shadow"
    assert records[0].candidate_action == "buy"
    assert records[0].metadata_json["features"]["rsi_norm"] == 0.1


def test_ai_observation_table_is_created_with_database_metadata(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'ai-schema.db'}")
    manager.create_tables()
    session = manager.SessionLocal()
    try:
        assert session.query(AIObservation).count() == 0
    finally:
        session.close()
