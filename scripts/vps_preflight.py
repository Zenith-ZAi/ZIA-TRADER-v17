"""Preflight de VPS para ZIA-TRADER-v17.

Não acessa endpoints de trading nem executa ordens. O modo estrito deve ser
usado antes de subir API/worker em um servidor persistente.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database_manager import DatabaseManager
from infra.redis_cache import RedisCache


TRUE_VALUES = {"1", "true", "yes", "on"}
REQUIRED_TABLES = {
    "account_state",
    "positions",
    "order_intents",
    "reconciliation_snapshots",
    "protection_orders",
    "kill_switch_events",
    "backtest_runs",
}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in TRUE_VALUES


def _safe_endpoint(value: str) -> str:
    if "@" in value:
        return value.rsplit("@", 1)[-1]
    return value.split("://", 1)[-1]


def run_preflight(strict: bool = False) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/zia_trader.db")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    live_flags = {
        name: _bool_env(name)
        for name in ("LIVE_TRADING_ENABLED", "LIVE_MODE", "AUTONOMOUS_TRADING_ENABLED", "MANUAL_TRADING_ENABLED")
    }
    safe_mode = not any(live_flags.values()) and _bool_env("SHADOW_MODE_ENABLED", True)
    add("trading_disabled", safe_mode, "flags de trading real/autônomo/manual devem permanecer false e shadow true")

    try:
        manager = DatabaseManager(database_url)
        with manager.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        manager.create_tables()
        tables = set(inspect(manager.engine).get_table_names())
        missing = sorted(REQUIRED_TABLES - tables)
        persistent_db = not database_url.startswith("sqlite:")
        add("database_reachable", True, f"endpoint={_safe_endpoint(database_url)}")
        add("database_schema", not missing, "schema completo" if not missing else f"tabelas ausentes: {missing}")
        require_db = _bool_env("REQUIRE_PERSISTENT_DATABASE", False)
        add("database_persistent", persistent_db or not require_db, "PostgreSQL" if persistent_db else "SQLite local/fallback")
    except Exception as exc:  # noqa: BLE001 - retorna diagnóstico legível
        add("database_reachable", False, f"falha: {type(exc).__name__}")
        add("database_schema", False, "não foi possível inspecionar o schema")
        add("database_persistent", False, "não foi possível confirmar persistência")

    try:
        cache = RedisCache(redis_url)
        persistent_redis = bool(cache.health().get("persistent"))
        require_redis = _bool_env("REQUIRE_PERSISTENT_REDIS", False)
        add("redis_reachable", True, cache.health().get("backend", "unknown"))
        add("redis_persistent", persistent_redis or not require_redis, "Redis" if persistent_redis else "fallback em memória")
    except Exception as exc:  # noqa: BLE001
        add("redis_reachable", False, f"falha: {type(exc).__name__}")
        add("redis_persistent", False, "não foi possível confirmar persistência")

    for path_value in (os.getenv("DATA_DIR", "data"), os.getenv("MODEL_DIR", "models"), os.getenv("LOG_DIR", "logs")):
        path = Path(path_value)
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".vps_preflight_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            add(f"filesystem:{path}", True, "diretório criado e gravável")
        except OSError as exc:
            add(f"filesystem:{path}", False, f"não gravável: {type(exc).__name__}")

    passed = all(item["passed"] for item in checks)
    return {
        "status": "passed" if passed else "blocked",
        "strict": strict,
        "live_flags": live_flags,
        "database_endpoint": _safe_endpoint(database_url),
        "redis_endpoint": _safe_endpoint(redis_url),
        "checks": checks,
        "next_action": "subir somente API/worker em modo shadow/paper" if passed else "corrigir os checks falhos antes do deploy",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida pré-requisitos seguros do VPS")
    parser.add_argument("--strict", action="store_true", help="retorna código 1 se qualquer check falhar")
    args = parser.parse_args()
    result = run_preflight(strict=args.strict)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.strict and result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
