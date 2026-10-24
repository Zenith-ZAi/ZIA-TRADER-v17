"""Startup invariants for production API and worker processes."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


_PLACEHOLDER_MARKERS = (
    "replace-with",
    "change-me",
    "dev-only",
    "placeholder",
    "your-secret",
    "example-password",
)


def production_configuration_errors(config: Any) -> list[str]:
    """Return safe-to-log configuration errors without exposing secret values."""
    environment = str(getattr(config, "ENVIRONMENT", "development")).strip().lower()
    if environment not in {"production", "prod", "staging"}:
        return []

    errors: list[str] = []
    secret = str(getattr(config, "SECRET_KEY", "") or "")
    if len(secret.encode("utf-8")) < 32 or any(marker in secret.lower() for marker in _PLACEHOLDER_MARKERS):
        errors.append("SECRET_KEY deve ter pelo menos 32 bytes e não pode ser valor padrão/placeholder")

    if bool(getattr(config, "DEMO_AUTH_ENABLED", True)):
        errors.append("DEMO_AUTH_ENABLED deve ser false fora de desenvolvimento")
    if str(getattr(config, "AUTH_MODE", "")).strip().lower() != "env":
        errors.append("AUTH_MODE deve ser env em produção")
    if not str(getattr(config, "AUTH_USERNAME", "") or "").strip():
        errors.append("AUTH_USERNAME não configurado")

    password = str(getattr(config, "AUTH_PASSWORD", "") or "")
    if len(password.encode("utf-8")) < 16 or any(
        marker in password.lower() for marker in _PLACEHOLDER_MARKERS
    ):
        errors.append("AUTH_PASSWORD deve ter pelo menos 16 bytes e não pode ser placeholder")

    required_false = (
        "AUTO_START_ENGINES",
        "LIVE_TRADING_ENABLED",
        "LIVE_MODE",
        "AUTONOMOUS_TRADING_ENABLED",
        "MANUAL_TRADING_ENABLED",
        "NEURAL_MODELS_ENABLED",
    )
    enabled = [name for name in required_false if bool(getattr(config, name, False))]
    if enabled:
        errors.append(f"flags de execução devem permanecer false: {', '.join(enabled)}")
    if not bool(getattr(config, "LIVE_KILL_SWITCH", False)):
        errors.append("LIVE_KILL_SWITCH deve permanecer true")
    if not bool(getattr(config, "SHADOW_MODE_ENABLED", False)):
        errors.append("SHADOW_MODE_ENABLED deve permanecer true durante homologação")

    if not bool(getattr(config, "REQUIRE_PERSISTENT_DATABASE", False)):
        errors.append("REQUIRE_PERSISTENT_DATABASE deve ser true")
    if not bool(getattr(config, "REQUIRE_PERSISTENT_REDIS", False)):
        errors.append("REQUIRE_PERSISTENT_REDIS deve ser true")
    database_scheme = urlparse(str(getattr(config, "DATABASE_URL", ""))).scheme.lower()
    if not database_scheme.startswith("postgresql"):
        errors.append("DATABASE_URL deve usar PostgreSQL persistente")
    redis_scheme = urlparse(str(getattr(config, "REDIS_URL", ""))).scheme.lower()
    if redis_scheme not in {"redis", "rediss"}:
        errors.append("REDIS_URL deve usar Redis persistente")
    if not bool(getattr(config, "REQUIRE_ALEMBIC_HEAD", False)):
        errors.append("REQUIRE_ALEMBIC_HEAD deve ser true")

    if str(getattr(config, "BINANCE_MODE", "simulated")).strip().lower() in {"live", "mainnet"}:
        errors.append("BINANCE_MODE live/mainnet não permitido neste estágio")

    return errors


def validate_startup_configuration(config: Any) -> None:
    """Fail closed before initializing DB, providers, or engine tasks."""
    errors = production_configuration_errors(config)
    if errors:
        raise RuntimeError("configuração de produção insegura: " + "; ".join(errors))
