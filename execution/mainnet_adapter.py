"""Adapter Binance mainnet explicitamente opt-in e fail-closed."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from execution.binance_adapter import BinanceAdapterError, BinanceSpotAdapter

logger = logging.getLogger(__name__)


class MainnetDisabledError(BinanceAdapterError):
    """O adapter mainnet não está habilitado por confirmação dupla."""


class BinanceMainnetAdapter(BinanceSpotAdapter):
    """Versão mainnet separada; nunca é selecionada por padrão."""

    ALLOWED_HOSTS = {"api.binance.com"}

    def __init__(self, settings: Any, session: Optional[Any] = None):
        self.kill_switch_enabled = bool(getattr(settings, "LIVE_KILL_SWITCH", False))
        if not bool(getattr(settings, "LIVE_TRADING_ENABLED", False)) or not bool(getattr(settings, "LIVE_MODE", False)):
            raise MainnetDisabledError("Mainnet desabilitada: LIVE_TRADING_ENABLED e LIVE_MODE devem ser true explicitamente.")
        if bool(getattr(settings, "SHADOW_MODE_ENABLED", True)):
            raise MainnetDisabledError("Mainnet bloqueada durante SHADOW_MODE_ENABLED=true.")
        settings.BINANCE_BASE_URL = str(getattr(settings, "BINANCE_LIVE_BASE_URL", "https://api.binance.com/api"))
        settings.BINANCE_MODE = "live"
        super().__init__(settings, session=session)

    def _validate_configuration(self) -> None:
        mode = str(getattr(self.settings, "BINANCE_MODE", "")).lower()
        host = self._normalize_base_url(self.settings.BINANCE_BASE_URL).split("/")[2]
        if mode != "live" or host != "api.binance.com":
            raise MainnetDisabledError("Adapter mainnet exige BINANCE_MODE=live e api.binance.com em HTTPS.")
        if not self.api_key or not self.secret_key:
            raise MainnetDisabledError("Credenciais Binance mainnet ausentes.")

    def activate_kill_switch(self, reason: str = "manual") -> Dict[str, Any]:
        self.kill_switch_enabled = True
        logger.critical("KILL SWITCH MAINNET ATIVADO: %s", reason)
        return {"enabled": True, "reason": reason}

    def deactivate_kill_switch(self, reason: str = "manual") -> Dict[str, Any]:
        self.kill_switch_enabled = False
        logger.warning("KILL SWITCH MAINNET desativado: %s", reason)
        return {"enabled": False, "reason": reason}

    async def cancel_all_open_orders(self) -> Dict[str, Any]:
        orders = await self.get_open_orders()
        results = []
        for order in orders:
            order_id = order.get("order_id") or order.get("orderId")
            if order_id:
                try:
                    results.append(await self.cancel_order(str(order_id)))
                except Exception as exc:
                    results.append({"status": "error", "order_id": str(order_id), "reason": str(exc)})
        return {"status": "success" if all(item.get("status") != "error" for item in results) else "partial", "cancelled": results}

    async def place_order(self, symbol: str, action: str, order_type: str, quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        if self.kill_switch_enabled:
            raise MainnetDisabledError("Kill switch ativo: novas entradas estão bloqueadas.")
        if not bool(getattr(self.settings, "LIVE_TRADING_ENABLED", False)) or not bool(getattr(self.settings, "LIVE_MODE", False)):
            raise MainnetDisabledError("Mainnet desabilitada durante a execução.")
        return await super().place_order(symbol, action, order_type, quantity, price)

    async def trigger_kill_switch(self, reason: str = "manual") -> Dict[str, Any]:
        self.activate_kill_switch(reason)
        return await self.cancel_all_open_orders()
