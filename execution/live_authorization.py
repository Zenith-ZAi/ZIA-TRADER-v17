"""Gates globais de autorização para qualquer adapter capaz de enviar ordens.

Este módulo não habilita execução. Adapters transacionais devem consultar
`live_submission_block_reason` imediatamente antes de qualquer efeito externo.
"""

from __future__ import annotations

from typing import Any


_READ_ONLY_ADAPTERS = {"b3", "yahoo", "stocks"}
_SIMULATED_BINANCE_MODES = {"simulated", "simulation", "mock", "testnet", "demo"}
_READ_ONLY_FOREX_MODES = {"paper", "public", "readonly", "read_only"}


def requires_live_authorization(settings: Any) -> bool:
    """Identifica rotas que podem alcançar um broker/exchange transacional.

    Desconhecidos falham fechados: somente adapters explicitamente conhecidos
    como read-only ou simulados ficam fora da autorização live dupla.
    """
    adapter = str(getattr(settings, "MARKET_ADAPTER", "binance")).strip().lower()
    market_type = str(getattr(settings, "MARKET_TYPE", "spot")).strip().lower()

    if adapter in _READ_ONLY_ADAPTERS:
        return False
    if adapter in {"ccxt", "mt5", "fix"}:
        return True
    if adapter == "binance":
        if market_type == "futures":
            # MarketConnector direciona esse caminho ao CCXTAdapter.
            return True
        mode = str(getattr(settings, "BINANCE_MODE", "simulated")).strip().lower()
        return mode not in _SIMULATED_BINANCE_MODES
    if adapter in {"forex", "fx"}:
        mode = str(getattr(settings, "FOREX_MODE", "paper")).strip().lower()
        return mode not in _READ_ONLY_FOREX_MODES
    return True


def live_submission_block_reason(settings: Any) -> str | None:
    """Retorna motivo de bloqueio até os três flags globais autorizarem live."""
    if getattr(settings, "LIVE_KILL_SWITCH", True) is not False:
        return "live kill switch ativo ou não confirmado como desativado"
    if getattr(settings, "LIVE_TRADING_ENABLED", False) is not True:
        return "LIVE_TRADING_ENABLED não autorizado"
    if getattr(settings, "LIVE_MODE", False) is not True:
        return "LIVE_MODE não autorizado"
    return None


def autonomous_submission_block_reason(settings: Any, redis_cache: Any) -> str | None:
    """Recheck infrastructure at the call boundary, never at construction only."""
    if getattr(settings, "AUTONOMOUS_TRADING_ENABLED", False) is not True:
        return "execução autônoma desabilitada"
    if getattr(settings, "REDIS_REQUIRED_FOR_AUTONOMOUS", True) is not False:
        if redis_cache is None or getattr(redis_cache, "is_persistent", False) is not True:
            return "autonomia bloqueada: Redis persistente obrigatório"
    return None


def execution_gate_status(settings: Any) -> dict[str, Any]:
    """Configuration diagnostics only; not risk, reconciliation or order permission."""
    required = requires_live_authorization(settings)
    reason = live_submission_block_reason(settings) if required else None
    shadow = getattr(settings, "SHADOW_MODE_ENABLED", True) is not False
    if required and reason is None and shadow:
        reason = "SHADOW_MODE_ENABLED ativo"
    return {
        "live_adapter_selected": required,
        "live_kill_switch": getattr(settings, "LIVE_KILL_SWITCH", True) is not False,
        "live_trading_enabled": getattr(settings, "LIVE_TRADING_ENABLED", False) is True,
        "live_mode": getattr(settings, "LIVE_MODE", False) is True,
        "manual_trading_enabled": getattr(settings, "MANUAL_TRADING_ENABLED", False) is True,
        "autonomous_trading_enabled": getattr(settings, "AUTONOMOUS_TRADING_ENABLED", False) is True,
        "auto_start_engines": getattr(settings, "AUTO_START_ENGINES", False) is True,
        "shadow_mode_enabled": shadow,
        "live_flags_passed": required and reason is None,
        "block_reason": reason,
        "assessment": "configuration_gates_only_not_order_authorization",
    }


def restore_persisted_kill_state(settings: Any, db_manager: Any, account_id: str) -> dict[str, Any]:
    """Restore emergency blocking; never auto-rearm from config or legacy events."""
    getter = getattr(db_manager, "get_latest_kill_switch", None)
    latest = None
    status = "kill_state_unavailable"
    if callable(getter):
        try:
            latest = getter(account_id)
            status = "kill_state_absent" if latest is None else "kill_state_loaded"
        except Exception:
            status = "kill_state_read_failed"
    valid = isinstance(latest, dict) and isinstance(latest.get("enabled"), bool)
    if not valid or latest["enabled"] is True or requires_live_authorization(settings):
        settings.LIVE_KILL_SWITCH = True
    if valid and latest["enabled"] is False and requires_live_authorization(settings):
        status = "automatic_live_rearm_not_supported"
    return {"restore_status": status, "live_kill_switch": getattr(settings, "LIVE_KILL_SWITCH", True) is not False}
