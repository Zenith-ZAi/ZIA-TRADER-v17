"""Orquestração segura de ordens manuais e decisões da IA."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Dict

from execution.market_connector import MarketConnector
from risk.risk_ai import RiskAI


class OrderManagerError(ValueError):
    pass


@dataclass
class PendingOrder:
    token: str
    order_data: Dict[str, Any]
    source: str


class OrderManager:
    """Mantém o kill-switch entre intenção e envio de uma ordem."""

    VALID_MODES = {"manual", "auto"}

    def __init__(self, settings: Any, market_connector: MarketConnector, execution_engine: Any):
        self.settings = settings
        self.market_connector = market_connector
        self.execution_engine = execution_engine
        self.db_manager = getattr(execution_engine, "db_manager", None)
        self.risk_ai = RiskAI(settings, self.db_manager) if self.db_manager is not None else None
        self.mode = str(getattr(settings, "ORDER_MANAGER_MODE", "manual")).lower()
        if self.mode not in self.VALID_MODES:
            raise OrderManagerError("ORDER_MANAGER_MODE deve ser manual ou auto")
        self.confirmation_required = bool(getattr(settings, "ORDER_CONFIRMATION_REQUIRED", True))
        self._pending: Dict[str, PendingOrder] = {}

    @staticmethod
    def parse_command(command: str, market: str = "crypto") -> Dict[str, Any]:
        match = re.fullmatch(r"\s*(comprar|vender|buy|sell)\s+([A-Za-z0-9_./-]+)\s+([0-9]+(?:[.,][0-9]+)?)\s*", command, flags=re.IGNORECASE)
        if not match:
            raise OrderManagerError("use: comprar BTC 0.01 ou vender EURUSD 1000")
        raw_action, raw_symbol, raw_quantity = match.groups()
        action = "buy" if raw_action.lower() in {"comprar", "buy"} else "sell"
        quantity = float(raw_quantity.replace(",", "."))
        if quantity <= 0:
            raise OrderManagerError("quantity deve ser positiva")
        compact = raw_symbol.upper().replace("-", "").replace("_", "")
        if market in {"forex", "fx"} and len(compact) == 6 and "/" not in raw_symbol:
            symbol = f"{compact[:3]}/{compact[3:]}"
        elif market in {"crypto", "binance"} and "/" not in raw_symbol:
            symbol = f"{compact[:-4]}/USDT" if compact.endswith("USDT") else f"{compact}/USDT"
        else:
            symbol = raw_symbol.upper()
        return {"symbol": symbol, "action": action, "order_type": "market", "quantity": quantity}

    def set_mode(self, mode: str) -> str:
        normalized = str(mode).lower().strip()
        if normalized not in self.VALID_MODES:
            raise OrderManagerError("mode deve ser manual ou auto")
        self.mode = normalized
        return self.mode

    def pending(self) -> list[Dict[str, Any]]:
        return [{"token": item.token, "source": item.source, "order_data": dict(item.order_data)} for item in self._pending.values()]

    async def submit(self, order_data: Dict[str, Any], source: str = "manual", confirmed: bool = False) -> Dict[str, Any]:
        source = str(source).lower()
        if source not in {"manual", "ai"}:
            raise OrderManagerError("source deve ser manual ou ai")
        if source == "ai" and self.mode != "auto":
            return {"status": "rejected", "source": source, "reason": "OrderManager está em modo manual"}
        if source == "manual" and self.mode != "manual":
            return {"status": "rejected", "source": source, "reason": "OrderManager está em modo auto"}
        normalized = dict(order_data)
        action = str(normalized.get("action", "")).lower()
        quantity = float(normalized.get("quantity", 0.0) or 0.0)
        if action not in {"buy", "sell"} or quantity <= 0 or not normalized.get("symbol"):
            raise OrderManagerError("ordem inválida")
        normalized["symbol"] = self.market_connector.canonical_symbol(str(normalized["symbol"]))
        if not normalized.get("price"):
            market = await self.market_connector.get_market_data(normalized["symbol"])
            normalized["price"] = float(market.get("last") or market.get("ask") or 0.0)
        if self.risk_ai is not None:
            account_state = self.db_manager.get_account_state("default_account")
            balances = await self.market_connector.get_account_balance()
            account_balance = self.risk_ai.quote_equivalent_balance(balances, normalized["symbol"], normalized["price"])
            if account_balance <= 0 and account_state is not None:
                account_balance = float(account_state.balance)
            validation = self.risk_ai.validate_order(
                normalized,
                account_balance,
                {"exchange_balances": balances},
            )
            if not validation.get("valid"):
                return {"status": "rejected", "source": source, "order": normalized, "reason": validation.get("reason", "risco rejeitado")}
            normalized.update(validation)
        normalized["source"] = source
        adapter_name = str(getattr(self.settings, "MARKET_ADAPTER", "binance")).lower()
        binance_live = adapter_name in {"binance", "ccxt"} and str(getattr(self.settings, "BINANCE_MODE", "simulated")).lower() in {"demo", "testnet", "live"}
        forex_live = adapter_name in {"forex", "fx"} and str(getattr(self.settings, "FOREX_MODE", "paper")).lower() == "live"
        if (binance_live or forex_live) and not bool(getattr(self.settings, "MANUAL_TRADING_ENABLED", False)) and not bool(getattr(self.settings, "AUTONOMOUS_TRADING_ENABLED", False)):
            return {"status": "rejected", "source": source, "order": normalized, "reason": "adapter live bloqueado: habilite manual trading ou autonomia explicitamente"}
        if self.confirmation_required and not confirmed:
            for pending in self._pending.values():
                same_symbol = pending.order_data.get("symbol") == normalized.get("symbol")
                same_action = pending.order_data.get("action") == normalized.get("action")
                if pending.source == source and same_symbol and same_action:
                    return {"status": "pending_confirmation", "confirmation_required": True, "confirmation_token": pending.token, "order": pending.order_data, "deduplicated": True}
            token = secrets.token_urlsafe(18)
            self._pending[token] = PendingOrder(token, normalized, source)
            return {"status": "pending_confirmation", "confirmation_required": True, "confirmation_token": token, "order": normalized}
        return await self._execute(normalized, source)

    async def confirm(self, token: str, approved: bool = True) -> Dict[str, Any]:
        pending = self._pending.pop(str(token), None)
        if pending is None:
            raise OrderManagerError("token de confirmação inexistente ou expirado")
        if not approved:
            return {"status": "cancelled", "confirmation_token": token, "order": pending.order_data}
        return await self._execute(pending.order_data, pending.source)

    async def _execute(self, order_data: Dict[str, Any], source: str) -> Dict[str, Any]:
        # A confirmação é o último gate; a execução continua centralizada e auditável.
        result = await self.execution_engine.execute_order(order_data)
        return {"status": result.get("status", "error"), "source": source, "order": order_data, "execution": result}
