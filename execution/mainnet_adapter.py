"""Adapter Binance mainnet explicitamente opt-in e fail-closed."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from execution.binance_adapter import BinanceAdapterError, BinanceSpotAdapter
from execution.live_authorization import live_submission_block_reason

logger = logging.getLogger(__name__)


class MainnetDisabledError(BinanceAdapterError):
    """O adapter mainnet não está habilitado por confirmação dupla."""


class BinanceMainnetAdapter(BinanceSpotAdapter):
    """Versão mainnet separada; nunca é selecionada por padrão."""

    ALLOWED_HOSTS = {"api.binance.com"}
    _ORDER_POST_PATHS = {"/v3/order", "/v3/order/oco", "/v3/orderList/oco"}

    def __init__(self, settings: Any, session: Optional[Any] = None):
        self.kill_switch_enabled = bool(getattr(settings, "LIVE_KILL_SWITCH", True))
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

    def _assert_live_write(self) -> None:
        reason = live_submission_block_reason(self.settings)
        if reason:
            raise MainnetDisabledError(f"Mainnet bloqueada: {reason}")
        if self.kill_switch_enabled:
            raise MainnetDisabledError("Kill switch ativo: submissões estão bloqueadas.")
        if getattr(self.settings, "SHADOW_MODE_ENABLED", True) is not False:
            raise MainnetDisabledError("Mainnet bloqueada durante SHADOW_MODE_ENABLED=true.")

    @staticmethod
    def _require_client_id(value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            raise MainnetDisabledError("Mainnet bloqueada: client_order_id idempotente é obrigatório.")

    async def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
        # Recheck after normalization/read-only awaits as well as at public methods.
        if method.upper() == "POST":
            if signed is not True:
                raise MainnetDisabledError("Mainnet bloqueada: POST deve ser assinado.")
            self._assert_live_write()
            if path not in self._ORDER_POST_PATHS:
                raise MainnetDisabledError("Mainnet bloqueada: endpoint transacional não homologado.")
            values = params or {}
            self._require_client_id(values.get("newClientOrderId") or values.get("listClientOrderId"))
        return await super()._request(method, path, params, signed=signed)

    def _before_transport_request(self, method: str, path: str, params: Optional[Dict[str, Any]]) -> None:
        if method.upper() == "POST":
            self._assert_live_write()
            if path not in self._ORDER_POST_PATHS:
                raise MainnetDisabledError("Mainnet bloqueada: endpoint transacional não homologado.")
            values = params or {}
            self._require_client_id(values.get("newClientOrderId") or values.get("listClientOrderId"))

    def activate_kill_switch(self, reason: str = "manual") -> Dict[str, Any]:
        self.kill_switch_enabled = True
        self.settings.LIVE_KILL_SWITCH = True
        logger.critical("KILL SWITCH MAINNET ATIVADO: %s", reason)
        return {"enabled": True, "reason": reason}

    def deactivate_kill_switch(self, reason: str = "manual") -> Dict[str, Any]:
        # Releasing the local latch cannot bypass the global setting or risk gates.
        self.kill_switch_enabled = False
        logger.warning("KILL SWITCH MAINNET local desativado: %s; gates globais preservados", reason)
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
                    results.append({"status": "error", "order_id": str(order_id), "reason": type(exc).__name__})
        return {"status": "success" if all(item.get("status") != "error" for item in results) else "partial", "cancelled": results}

    async def place_order(
        self,
        symbol: str,
        action: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_live_write()
        self._require_client_id(client_order_id)
        return await super().place_order(symbol, action, order_type, quantity, price, client_order_id=client_order_id)

    async def place_protection_order(self, protection: Dict[str, Any]) -> Dict[str, Any]:
        self._assert_live_write()
        self._require_client_id(protection.get("client_order_id"))
        return await super().place_protection_order(protection)

    async def trigger_kill_switch(self, reason: str = "manual") -> Dict[str, Any]:
        self.activate_kill_switch(reason)
        return await self.cancel_all_open_orders()
