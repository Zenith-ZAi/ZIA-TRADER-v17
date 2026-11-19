from __future__ import annotations

import asyncio
import ast
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from scripts.sandbox_backend_smoke import (
    MAX_LIMIT,
    SmokeConfigurationError,
    run_sandbox_backend_smoke,
)


class MockHTTP:
    def __init__(self, payload: list[list[Any]]):
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    async def get_json(self, provider: str, url: str, *, params: dict[str, Any]) -> Any:
        self.calls.append((provider, url, params))
        return self.payload

    async def aclose(self) -> None:
        self.closed = True


class FailingHTTP(MockHTTP):
    async def get_json(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls.append(("binance_public", "public", {}))
        raise RuntimeError("provider-secret-should-never-be-returned")


def binance_payload(count: int = 100) -> list[list[Any]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows: list[list[Any]] = []
    for index in range(count):
        opened = start + timedelta(hours=index)
        closed = opened + timedelta(hours=1) - timedelta(milliseconds=1)
        open_price = 40_000.0 + index
        close_price = open_price + 2.0
        rows.append(
            [
                int(opened.timestamp() * 1000),
                f"{open_price:.8f}",
                f"{open_price + 8.0:.8f}",
                f"{open_price - 3.0:.8f}",
                f"{close_price:.8f}",
                f"{1000.0 + index:.8f}",
                int(closed.timestamp() * 1000),
            ]
        )
    return rows


def test_success_persists_closed_candles_and_reimports_idempotently_without_second_http(tmp_path: Path) -> None:
    http = MockHTTP(binance_payload(100))
    result = asyncio.run(
        run_sandbox_backend_smoke(http=http, output_dir=tmp_path, limit=100)
    )

    assert result["status"] == "ok"
    assert result["request"] == {
        "source": "binance_public",
        "asset_class": "crypto",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "limit": 100,
    }
    assert result["rows"]["received"] == 100
    assert result["rows"]["persisted"] == 100
    assert result["rows"]["stored_before_reimport"] == 100
    assert result["rows"]["stored_after_reimport"] == 100
    assert result["idempotency"] == {"count_unchanged": True, "http_calls": 1}
    assert result["checks"]["idempotent_reimport"] is True
    assert result["checks"]["closed_candles_persisted"] is True
    assert result["features"]["rows"] == 100
    assert result["features"]["valid"] is True
    assert len(result["features"]["sha256"]) == 64
    assert result["decision"]["action"] == "HOLD"
    assert result["news"] == {"status": "not_requested"}
    assert result["orders_sent"] == 0
    assert http.closed is True
    assert len(http.calls) == 1

    database_path = tmp_path / "sandbox_backend_smoke.sqlite"
    assert database_path.is_file()
    with sqlite3.connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM market_candles").fetchone()[0]
    assert count == 100
    artifact = json.loads((tmp_path / "sandbox_backend_smoke.json").read_text(encoding="utf-8"))
    assert artifact["status"] == "ok"
    assert "SECRET" not in json.dumps(artifact).upper()


def test_source_failure_is_attention_safe_and_does_not_fabricate_candles(tmp_path: Path) -> None:
    http = FailingHTTP([])
    result = asyncio.run(
        run_sandbox_backend_smoke(http=http, output_dir=tmp_path, limit=100)
    )

    assert result["status"] == "attention"
    assert result["error_code"] == "upstream_unavailable"
    assert result["rows"]["received"] == 0
    assert result["rows"]["persisted"] == 0
    assert result["rows"]["stored_after_reimport"] == 0
    assert "provider-secret-should-never-be-returned" not in json.dumps(result)
    assert "secret" not in json.dumps(result).lower()
    assert http.closed is True

    database_path = tmp_path / "sandbox_backend_smoke.sqlite"
    with sqlite3.connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM market_candles").fetchone()[0]
    assert count == 0


def test_output_dir_must_be_empty_and_limit_is_bounded(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "existing.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(SmokeConfigurationError) as occupied_error:
        asyncio.run(run_sandbox_backend_smoke(http=MockHTTP(binance_payload()), output_dir=occupied))
    assert occupied_error.value.code == "output_dir_not_empty"

    with pytest.raises(SmokeConfigurationError) as limit_error:
        asyncio.run(run_sandbox_backend_smoke(http=MockHTTP(binance_payload()), limit=MAX_LIMIT + 1))
    assert limit_error.value.code == "limit_out_of_range"


def test_smoke_source_has_no_execution_adapter_imports() -> None:
    source_path = Path(__file__).resolve().parents[1] / "scripts" / "sandbox_backend_smoke.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    assert all(not module == "execution" and not module.startswith("execution.") for module in imported_modules)


def test_insufficient_features_is_attention_not_success(tmp_path: Path) -> None:
    result = asyncio.run(run_sandbox_backend_smoke(http=MockHTTP(binance_payload(1)), output_dir=tmp_path, limit=1))
    assert result["status"] == "attention"
    assert result["features"]["valid"] is False
    assert result["decision"]["action"] == "HOLD"
    assert result["orders_sent"] == 0


def test_smoke_does_not_inherit_live_flags_or_change_environment(tmp_path: Path, monkeypatch) -> None:
    import os
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("BINANCE_API_KEY", "dummy-test-key-never-used")
    before = dict(os.environ)
    result = asyncio.run(run_sandbox_backend_smoke(http=MockHTTP(binance_payload(100)), output_dir=tmp_path))
    assert result["status"] == "ok"
    assert result["orders_sent"] == 0
    assert result["analysis"]["execution_authorized"] is False
    assert dict(os.environ) == before
    assert "dummy-test-key-never-used" not in json.dumps(result)
