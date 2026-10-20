"""Orquestração segura de ordens manuais e decisões da IA."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from execution.market_connector import MarketConnector
from risk.risk_ai import RiskAI
from core.risk_guard import evaluate_circuit_breaker


class OrderManagerError(ValueError):
    pass


@dataclass
class PendingOrder:
    token: str
    order_data: Dict[str, Any]
    source: str
    market_context: Dict[str, Any] = field(default_factory=dict)


class OrderManager:
    """Mantém autorização e gates de segurança entre intenção e envio."""

    VALID_MODES = {"manual", "auto"}

    def __init__(self, settings: Any, market_connector: MarketConnector, execution_engine: Any):
        self.settings = settings
        self.market_connector = market_connector
        self.execution_engine = execution_engine
        self.db_manager = getattr(execution_engine, "db_manager", None)
        self.account_id = str(getattr(execution_engine, "account_id", "default_account"))
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

    def _live_adapter_selected(self) -> bool:
        adapter = str(getattr(self.settings, "MARKET_ADAPTER", "binance")).lower()
        binance_live = adapter in {"binance", "ccxt"} and str(getattr(self.settings, "BINANCE_MODE", "simulated")).lower() == "live"
        forex_live = adapter in {"forex", "fx"} and str(getattr(self.settings, "FOREX_MODE", "paper")).lower() == "live"
        return bool(binance_live or forex_live)

    def _authorized(self, source: str, order_data: Dict[str, Any]) -> str | None:
        if source == "ai":
            if self.mode != "auto":
                return "OrderManager está em modo manual"
            if not bool(getattr(self.settings, "AUTONOMOUS_TRADING_ENABLED", False)):
                return "execução autônoma desabilitada"
            if order_data.get("signal_validated") is not True:
                return "decisão de IA sem autorização de sinal validada pelo motor"
        elif self.mode != "manual":
            return "OrderManager está em modo auto"
        elif not bool(getattr(self.settings, "MANUAL_TRADING_ENABLED", False)):
            return "negociação manual desabilitada"

        if self._live_adapter_selected():
            if not bool(getattr(self.settings, "MANUAL_TRADING_ENABLED", False)) and source == "manual":
                return "ordem manual bloqueada para adapter live"
            if not bool(getattr(self.settings, "AUTONOMOUS_TRADING_ENABLED", False)) and source == "ai":
                return "ordem autônoma bloqueada para adapter live"
            if bool(getattr(self.settings, "LIVE_KILL_SWITCH", True)):
                return "live kill switch ativo"
            if not bool(getattr(self.settings, "LIVE_TRADING_ENABLED", False)) or not bool(getattr(self.settings, "LIVE_MODE", False)):
                return "adapter live bloqueado pelos flags de autorização"
        return None

    async def _ensure_execution_ready(self, source: str) -> str | None:
        if not bool(getattr(self.market_connector, "is_connected", False)):
            return "adapter desconectado; envio bloqueado"
        if not callable(getattr(self.market_connector, "place_order", None)):
            return "adapter sem capacidade de submissão"
        reconciler = getattr(self.execution_engine, "reconciler", None)
        if reconciler is None or not callable(getattr(reconciler, "reconcile", None)):
            return "reconciliador/idempotência indisponível; envio bloqueado"
        try:
            result = await reconciler.reconcile()
        except Exception as exc:
            return f"reconciliação falhou; envio bloqueado: {exc}"
        if not isinstance(result, dict) or result.get("status") != "ok":
            return f"reconciliação não está saudável/completa; envio bloqueado: {result}"
        return None

    def _circuit_breaker_reason(self, account_balance: float, account_state: Any) -> str | None:
        if account_state is None:
            return "estado persistente da conta indisponível; entrada bloqueada"
        daily = self.db_manager.get_daily_pnl(self.account_id, datetime.now(timezone.utc).replace(tzinfo=None))
        assessment = evaluate_circuit_breaker(
            account_balance,
            float(account_state.initial_capital or 0.0),
            float(daily.pnl) if daily is not None else 0.0,
            self.settings,
        )
        return assessment["reason"] if assessment["tripped"] else None

    async def submit(
        self,
        order_data: Dict[str, Any],
        source: str = "manual",
        confirmed: bool = False,
        market_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        source = str(source).lower()
        if source not in {"manual", "ai"}:
            raise OrderManagerError("source deve ser manual ou ai")
        normalized = dict(order_data)
        authorization_error = self._authorized(source, normalized)
        if authorization_error:
            return {"status": "rejected", "source": source, "reason": authorization_error}

        action = str(normalized.get("action", "")).lower()
        try:
            quantity = float(normalized.get("quantity", 0.0) or 0.0)
        except (TypeError, ValueError):
            quantity = 0.0
        if action not in {"buy", "sell"} or quantity <= 0 or not normalized.get("symbol"):
            raise OrderManagerError("ordem inválida")
        normalized["symbol"] = self.market_connector.canonical_symbol(str(normalized["symbol"]))
        signal_validated = normalized.pop("signal_validated", False)
        if source == "ai" and signal_validated is not True:
            return {"status": "rejected", "source": source, "reason": "decisão de IA sem autorização de sinal validada pelo motor"}
        if not normalized.get("price"):
            try:
                market = await self.market_connector.get_market_data(normalized["symbol"])
                normalized["price"] = float(market.get("last") or market.get("ask") or 0.0)
            except Exception as exc:
                return {"status": "rejected", "source": source, "reason": f"cotação indisponível: {exc}"}

        if self.risk_ai is None or self.db_manager is None:
            return {"status": "rejected", "source": source, "reason": "validador/persistência de risco indisponível"}
        try:
            balances = await self.market_connector.get_account_balance()
        except Exception as exc:
            return {"status": "rejected", "source": source, "reason": f"saldo da exchange indisponível: {exc}"}
        if not isinstance(balances, dict):
            return {"status": "rejected", "source": source, "reason": "resposta de saldo inválida"}
        account_state = self.db_manager.get_account_state(self.account_id)
        account_balance = self.risk_ai.quote_equivalent_balance(balances, normalized["symbol"], float(normalized["price"]))
        if account_balance <= 0 and not self._live_adapter_selected() and source == "manual" and account_state is not None:
            account_balance = float(account_state.balance or 0.0)
        if account_balance <= 0:
            return {"status": "rejected", "source": source, "reason": "saldo verificável insuficiente/indisponível"}
        circuit_error = self._circuit_breaker_reason(account_balance, account_state)
        if circuit_error:
            return {"status": "rejected", "source": source, "reason": circuit_error}

        context = dict(market_context or {})
        context["exchange_balances"] = balances
        context["execution_source"] = source
        validation = self.risk_ai.validate_order(normalized, account_balance, context)
        if not validation.get("valid"):
            return {"status": "rejected", "source": source, "order": normalized, "reason": validation.get("reason", "risco rejeitado"), "risk": validation}
        normalized.update(validation)
        normalized["source"] = source
        normalized.pop("signal_validated", None)

        readiness_error = await self._ensure_execution_ready(source)
        if readiness_error:
            return {"status": "rejected", "source": source, "order": normalized, "reason": readiness_error}
        if self.confirmation_required and not confirmed:
            for pending in self._pending.values():
                same_symbol = pending.order_data.get("symbol") == normalized.get("symbol")
                same_action = pending.order_data.get("action") == normalized.get("action")
                if pending.source == source and same_symbol and same_action:
                    return {"status": "pending_confirmation", "confirmation_required": True, "confirmation_token": pending.token, "order": pending.order_data, "deduplicated": True}
            token = secrets.token_urlsafe(18)
            self._pending[token] = PendingOrder(token, normalized, source, context)
            return {"status": "pending_confirmation", "confirmation_required": True, "confirmation_token": token, "order": normalized}
        return await self._execute(normalized, source)

    async def confirm(self, token: str, approved: bool = True) -> Dict[str, Any]:
        pending = self._pending.pop(str(token), None)
        if pending is None:
            raise OrderManagerError("token de confirmação inexistente ou expirado")
        if not approved:
            return {"status": "cancelled", "confirmation_token": token, "order": pending.order_data}
        # Revalida autorização, saldo, risco, circuito e reconciliação no instante da confirmação.
        order = dict(pending.order_data)
        order.pop("source", None)
        return await self.submit(order, source=pending.source, confirmed=True, market_context=pending.market_context)

    async def submit_exit(
        self,
        order_data: Dict[str, Any],
        source: str = "ai",
        market_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Executa somente a redução de uma posição persistida; não abre nova exposição."""
        source = str(source).lower()
        if source != "ai" or not bool(getattr(self.settings, "AUTONOMOUS_TRADING_ENABLED", False)):
            return {"status": "rejected", "source": source, "reason": "saída automática não autorizada"}
        if self.risk_ai is None or self.db_manager is None:
            return {"status": "rejected", "source": source, "reason": "validador/persistência de risco indisponível"}
        symbol = self.market_connector.canonical_symbol(str(order_data.get("symbol") or ""))
        try:
            price = float(order_data.get("price", 0.0))
        except (TypeError, ValueError):
            price = 0.0
        positions = self.db_manager.get_open_runtime_positions(self.account_id)
        persisted = next((item for item in positions if self.market_connector.canonical_symbol(item.symbol) == symbol), None)
        if persisted is None:
            return {"status": "rejected", "source": source, "reason": "posição aberta persistida não encontrada; saída bloqueada"}
        position = {
            "symbol": symbol,
            "action": str(persisted.action),
            "quantity": float(persisted.quantity),
            "entry_price": float(persisted.entry_price),
            "exit_reason": str(order_data.get("exit_reason") or "policy"),
        }
        context = dict(market_context or {})
        try:
            context["exchange_balances"] = await self.market_connector.get_account_balance()
        except Exception as exc:
            return {"status": "rejected", "source": source, "reason": f"saldo para validar saída indisponível: {exc}"}
        validation = self.risk_ai.validate_exit(position, price, context)
        if not validation.get("valid"):
            return {"status": "rejected", "source": source, "reason": validation.get("reason", "saída rejeitada pelo risco")}
        payload = {**validation, "market_type": order_data.get("market_type"), "exit_reason": position["exit_reason"]}
        return await self._execute(payload, source)

    async def _execute(self, order_data: Dict[str, Any], source: str) -> Dict[str, Any]:
        # Último gate imediatamente antes do envio; mantém a execução centralizada.
        readiness_error = await self._ensure_execution_ready(source)
        if readiness_error:
            return {"status": "rejected", "source": source, "order": order_data, "reason": readiness_error}
        result = await self.execution_engine.execute_order(order_data)
        return {"status": result.get("status", "error"), "source": source, "order": order_data, "execution": result}
