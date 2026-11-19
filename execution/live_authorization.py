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
