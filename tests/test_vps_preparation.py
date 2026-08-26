from __future__ import annotations

from pathlib import Path

from database_manager import DatabaseManager
from scripts.vps_preflight import run_preflight


def test_backtest_run_is_persisted_and_nonfinite_values_are_sanitized(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'vps.db'}"
    manager = DatabaseManager(database_url)
    manager.create_tables()
    result = manager.create_backtest_run(
        run_id="test-monthly-001",
        symbol="BTCUSDT",
        timeframe="1h",
        dataset_path="data/test.csv",
        dataset_sha256="abc123",
        result={
            "status": "ok",
            "start_date": "2026-01-01T00:00:00+00:00",
            "end_date": "2026-01-31T00:00:00+00:00",
            "initial_capital": 10000.0,
            "final_capital": 10050.0,
            "total_pnl": 50.0,
            "return_pct": 0.005,
            "sharpe_ratio": 0.4,
            "maximum_drawdown": -0.02,
            "trades_executed": 3,
            "profit_factor": float("inf"),
        },
        configuration={"orders_sent": 0},
    )
    assert result["status"] == "ok"
    rows = manager.list_backtest_runs("BTCUSDT")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "test-monthly-001"
    assert rows[0]["trades_executed"] == 3


def test_preflight_blocks_when_persistent_services_are_required(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'strict.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:63999/0")
    monkeypatch.setenv("REQUIRE_PERSISTENT_DATABASE", "true")
    monkeypatch.setenv("REQUIRE_PERSISTENT_REDIS", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("AUTONOMOUS_TRADING_ENABLED", "false")
    monkeypatch.setenv("MANUAL_TRADING_ENABLED", "false")
    monkeypatch.setenv("SHADOW_MODE_ENABLED", "true")

    result = run_preflight(strict=True)
    assert result["status"] == "blocked"
    assert any(check["name"] == "database_persistent" and not check["passed"] for check in result["checks"])
    assert any(check["name"] == "redis_persistent" and not check["passed"] for check in result["checks"])


def test_preflight_local_safe_defaults_pass(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'preflight.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:63999/0")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("REQUIRE_PERSISTENT_DATABASE", "false")
    monkeypatch.setenv("REQUIRE_PERSISTENT_REDIS", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("AUTONOMOUS_TRADING_ENABLED", "false")
    monkeypatch.setenv("MANUAL_TRADING_ENABLED", "false")
    monkeypatch.setenv("SHADOW_MODE_ENABLED", "true")

    result = run_preflight(strict=True)
    assert result["status"] == "passed"
    assert all(check["passed"] for check in result["checks"])
