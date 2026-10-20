from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.settings import Settings
from database_manager import DatabaseManager
from risk.risk_ai import RiskAI


def make_risk(tmp_path):
    settings = Settings(DATABASE_URL=f"sqlite:///{tmp_path / 'risk.db'}", CIRCUIT_BREAKER_ENABLED=False)
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    db.create_or_update_account_state("default_account", 10000.0, 10000.0)
    risk = RiskAI(settings, db)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    snapshot = {
        "account_id": "default_account",
        "source": "equity_ledger_v1",
        "complete": True,
        "fees_included": True,
        "funding_included": True,
        "external_flows_adjusted": True,
        "ledger_consistent": True,
        "updated_at": now.isoformat(),
        "daily": {"period_start": day_start.isoformat(), "starting_equity": 10000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
        "weekly": {"period_start": week_start.isoformat(), "starting_equity": 10000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
        "monthly": {"period_start": month_start.isoformat(), "starting_equity": 10000.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
    }
    db.get_verified_risk_periods = lambda account_id, as_of: snapshot
    order = {"symbol": "BTC/USDT", "action": "buy", "price": 100.0, "confidence": 0.95}
    context = {"execution_source": "ai"}
    return risk, db, snapshot, order, context


def test_missing_verified_period_ledger_blocks_new_execution_entries(tmp_path):
    risk, db, _, order, context = make_risk(tmp_path)
    db.get_verified_risk_periods = lambda account_id, as_of: None
    result = risk.validate_order(order, 10000.0, context)
    assert not result["valid"]
    assert "diário/semanal/mensal indisponível" in result["reason"]


def test_daily_period_loss_limit_blocks_new_execution_entries(tmp_path):
    risk, _, snapshot, order, context = make_risk(tmp_path)
    snapshot["daily"]["realized_pnl"] = -500.0
    result = risk.validate_order(order, 10000.0, context)
    assert not result["valid"]
    assert result["period_risk"]["status"] == "daily_loss_limit_reached"


def test_weekly_and_monthly_period_loss_limits_block_new_entries(tmp_path):
    risk, _, snapshot, order, context = make_risk(tmp_path)
    snapshot["weekly"]["realized_pnl"] = -1000.0
    weekly_result = risk.validate_order(order, 10000.0, context)
    assert not weekly_result["valid"]
    assert weekly_result["period_risk"]["status"] == "weekly_loss_limit_reached"

    snapshot["weekly"]["realized_pnl"] = 0.0
    snapshot["monthly"]["unrealized_pnl"] = -1500.0
    monthly_result = risk.validate_order(order, 10000.0, context)
    assert not monthly_result["valid"]
    assert monthly_result["period_risk"]["status"] == "monthly_loss_limit_reached"


def test_incomplete_stale_or_wrong_account_period_snapshot_fails_closed(tmp_path):
    risk, _, snapshot, order, context = make_risk(tmp_path)
    snapshot["fees_included"] = False
    incomplete = risk.validate_order(order, 10000.0, context)
    assert not incomplete["valid"]
    assert incomplete["period_risk"]["status"] == "period_ledger_unverified"

    snapshot["fees_included"] = True
    snapshot["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    stale = risk.validate_order(order, 10000.0, context)
    assert not stale["valid"]
    assert stale["period_risk"]["status"] == "period_ledger_unverified"

    snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["account_id"] = "other"
    wrong_account = risk.validate_order(order, 10000.0, context)
    assert not wrong_account["valid"]


def test_shadow_validation_does_not_require_execution_period_ledger(tmp_path):
    risk, db, _, order, _ = make_risk(tmp_path)
    db.get_verified_risk_periods = lambda account_id, as_of: None
    result = risk.validate_order(order, 10000.0, {})
    assert result["valid"]
    assert result["period_risk"]["status"] == "not_execution_path"


def trade_samples(count, return_value=0.01, *, reverse=False, duplicate=False):
    now = datetime.now(timezone.utc)
    samples = [
        {
            "execution_id": f"exec-{i}",
            "closed_at": (now - timedelta(minutes=count - i)).isoformat(),
            "return_pct": return_value,
        }
        for i in range(count)
    ]
    if reverse:
        samples.reverse()
    if duplicate and samples:
        samples[-1]["execution_id"] = samples[0]["execution_id"]
    return samples


def verified_ledger(account_id, samples):
    return {
        "account_id": account_id,
        "source": "closed_execution_ledger_v1",
        "complete": True,
        "fees_included": True,
        "funding_included": True,
        "external_flows_adjusted": True,
        "returns": samples,
    }


def test_kelly_requires_verified_realized_unique_chronological_samples(tmp_path):
    risk, db, _, order, _ = make_risk(tmp_path)
    samples = trade_samples(19)
    db.get_verified_trade_returns = lambda account_id, limit: verified_ledger(account_id, samples)
    below = risk.validate_order(order, 10000.0, {
        "realized_trade_returns": trade_samples(100, return_value=0.99),
        "trade_returns_verified": True,
        "trade_returns_source": "closed_execution_ledger_v1",
    })
    assert below["valid"]
    assert below["adaptive_kelly"] is None
    assert below["adaptive_kelly_status"] == "insufficient_history"

    samples[:] = trade_samples(20)
    exactly = risk.validate_order(order, 10000.0, {})
    assert exactly["valid"]
    assert exactly["adaptive_kelly"]["observations"] == 20
    assert exactly["adaptive_kelly_status"] == "verified"
    assert exactly["risk_fraction"] <= risk.max_risk_per_trade

    samples[:] = trade_samples(21)
    above = risk.validate_order(order, 10000.0, {})
    assert above["valid"]
    assert above["adaptive_kelly"]["observations"] == 21


def test_unverified_legacy_invalid_and_nonchronological_returns_are_ignored(tmp_path):
    risk, db, _, order, _ = make_risk(tmp_path)
    legacy = risk.validate_order(order, 10000.0, {
        "trade_returns": [0.02] * 30,
        "realized_trade_returns": trade_samples(30, return_value=0.02),
        "trade_returns_verified": True,
        "trade_returns_source": "closed_execution_ledger_v1",
    })
    assert legacy["valid"]
    assert legacy["adaptive_kelly"] is None
    assert legacy["adaptive_kelly_status"] == "unverified_or_missing_source"

    db.get_verified_trade_returns = lambda account_id, limit: verified_ledger(account_id, trade_samples(20, duplicate=True))
    duplicate = risk.validate_order(order, 10000.0, {})
    assert duplicate["valid"]
    assert duplicate["adaptive_kelly"] is None
    assert duplicate["adaptive_kelly_status"] == "invalid_sample"

    db.get_verified_trade_returns = lambda account_id, limit: verified_ledger(account_id, trade_samples(20, reverse=True))
    non_chronological = risk.validate_order(order, 10000.0, {})
    assert non_chronological["valid"]
    assert non_chronological["adaptive_kelly"] is None
    assert non_chronological["adaptive_kelly_status"] == "non_chronological_samples"


def test_kelly_blocks_new_entries_without_positive_edge_and_exits_remain_available(tmp_path):
    risk, db, _, order, _ = make_risk(tmp_path)
    db.get_verified_trade_returns = lambda account_id, limit: verified_ledger(account_id, trade_samples(20, return_value=-0.01))
    losses = risk.validate_order(order, 10000.0, {})
    assert not losses["valid"]
    assert "Kelly adaptativo" in losses["reason"]

    exit_result = risk.validate_exit({"symbol": "BTC/USDT", "action": "buy", "quantity": 0.1}, 100.0)
    assert exit_result["valid"]


def test_kelly_rejects_stale_and_future_samples_and_does_not_survive_restart_without_ledger(tmp_path):
    risk, db, _, order, _ = make_risk(tmp_path)
    stale = trade_samples(20)
    stale[0]["closed_at"] = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    db.get_verified_trade_returns = lambda account_id, limit: verified_ledger(account_id, stale)
    stale_result = risk.validate_order(order, 10000.0, {})
    assert stale_result["valid"]
    assert stale_result["adaptive_kelly"] is None
    assert stale_result["adaptive_kelly_status"] == "invalid_sample"

    future = trade_samples(20)
    future[-1]["closed_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    db.get_verified_trade_returns = lambda account_id, limit: verified_ledger(account_id, future)
    future_result = risk.validate_order(order, 10000.0, {})
    assert future_result["adaptive_kelly"] is None
    assert future_result["adaptive_kelly_status"] == "invalid_sample"

    restarted_db = DatabaseManager(risk.settings.DATABASE_URL)
    restarted_risk = RiskAI(risk.settings, restarted_db)
    spoofed = restarted_risk.validate_order(order, 10000.0, {
        "realized_trade_returns": trade_samples(50, return_value=0.99),
        "trade_returns_verified": True,
        "trade_returns_source": "closed_execution_ledger_v1",
    })
    assert spoofed["valid"]
    assert spoofed["adaptive_kelly"] is None
    assert spoofed["adaptive_kelly_status"] == "unverified_or_missing_source"
    restarted_db.engine.dispose()
