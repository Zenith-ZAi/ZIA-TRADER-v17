"""Preflight de VPS para ZIA-TRADER-v17.

Não acessa endpoints de trading nem executa ordens. O modo estrito deve ser
usado antes de subir API/worker em um servidor persistente.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database_manager import DatabaseManager
from infra.redis_cache import RedisCache
from config.settings import Settings
from config.startup_validation import production_configuration_errors


TRUE_VALUES = {"1", "true", "yes", "on"}
REQUIRED_TABLES = {
    "account_state",
    "positions",
    "order_intents",
    "reconciliation_snapshots",
    "protection_orders",
    "kill_switch_events",
    "backtest_runs",
    "decision_snapshots",
}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in TRUE_VALUES


def _safe_endpoint(value: str) -> str:
    if "@" in value:
        return value.rsplit("@", 1)[-1]
    return value.split("://", 1)[-1]


def _alembic_head_status(engine) -> tuple[bool, str]:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return False, "tabela alembic_version ausente"
    with engine.connect() as connection:
        current_heads = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if not expected_heads or current_heads != expected_heads:
        return False, f"revisão atual={sorted(current_heads)}; esperada={sorted(expected_heads)}"
    return True, f"revisão aplicada={sorted(current_heads)}"


def run_preflight(strict: bool = False) -> dict[str, Any]:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/zia_trader.db")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    security_errors = production_configuration_errors(Settings())
    add(
        "startup_security_configuration",
        not security_errors,
        "configuração compatível com startup" if not security_errors else "; ".join(security_errors),
    )

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
        if _bool_env("REQUIRE_ALEMBIC_HEAD", False):
            migration_ok, migration_detail = _alembic_head_status(manager.engine)
            add("alembic_head", migration_ok, migration_detail)
        else:
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

    add("alert_rules_file", (PROJECT_ROOT / "deploy" / "alert_rules.yml").is_file(), "regras Prometheus presentes")
    if _bool_env("REQUIRE_TLS_PROXY", False):
        cert_dir = Path(os.getenv("TLS_CERT_DIR", str(PROJECT_ROOT / "deploy" / "tls")))
        cert_path = cert_dir / "fullchain.pem"
        key_path = cert_dir / "privkey.pem"
        add("nginx_config", (PROJECT_ROOT / "deploy" / "nginx.conf").is_file(), "configuração Nginx presente")
        add("tls_certificate", cert_path.is_file(), "certificado TLS presente" if cert_path.is_file() else "gere certificado real; autoassinado só serve para teste")
        add("tls_private_key", key_path.is_file() and key_path.stat().st_mode & 0o077 == 0, "chave TLS presente e restrita")
        tls_url = os.getenv("TLS_PREFLIGHT_URL", "https://127.0.0.1:8443/")
        parsed = urlparse(tls_url)
        tls_ok = False
        tls_detail = "endpoint TLS não testado"
        try:
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("TLS_PREFLIGHT_URL inválida")
            port = parsed.port or 443
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection((parsed.hostname, port), timeout=3) as raw:
                with context.wrap_socket(raw, server_hostname=parsed.hostname) as secure:
                    tls_ok = secure.version() in {"TLSv1.2", "TLSv1.3"}
                    tls_detail = secure.version() or "versão TLS desconhecida"
        except Exception as exc:
            tls_detail = f"falha: {type(exc).__name__}"
        add("nginx_tls_reachable", tls_ok, tls_detail)
    if _bool_env("FIREWALL_PREFLIGHT_REQUIRED", False):
        add("firewall_tool", shutil.which("iptables") is not None, "iptables disponível; regras devem ser auditadas no VPS")

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
