"""Reconciliação e idempotência para execução segura de ordens."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


class ReconciliationError(RuntimeError):
    """Falha em uma reconciliação que não deve ser ignorada."""


class OrderReconciler:
    """Mantém a intenção local consistente com a exchange.

    O retry só é considerado seguro quando o adapter preserva ``client_order_id``
    e o mesmo identificador é reutilizado em todas as tentativas. O reconciler
    nunca presume que uma falha de transporte significa que a exchange não recebeu
    a ordem; por isso, consulta a intenção e a ordem aberta antes de tentar de novo.
    """

    TERMINAL_STATUSES = {"filled", "canceled", "cancelled", "rejected", "expired", "failed"}

    def __init__(
        self,
        db_manager: Any,
        exchange_connector: Any,
        redis_cache: Any | None = None,
        account_id: str = "default_account",
        max_attempts: int = 3,
        base_delay_seconds: float = 0.25,
        max_delay_seconds: float = 4.0,
    ) -> None:
        self.db_manager = db_manager
        self.exchange_connector = exchange_connector
        self.redis_cache = redis_cache
        self.account_id = account_id
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay_seconds = max(0.0, float(base_delay_seconds))
        self.max_delay_seconds = max(self.base_delay_seconds, float(max_delay_seconds))

    @staticmethod
    def new_client_order_id(symbol: str, action: str) -> str:
        prefix = hashlib.sha1(f"{symbol}:{action}".encode("utf-8")).hexdigest()[:8]
        return f"zia_{prefix}_{uuid.uuid4().hex[:18]}"

    def reserve(self, order_data: Dict[str, Any], client_order_id: str | None = None) -> Dict[str, Any]:
        client_id = client_order_id or str(order_data.get("client_order_id") or self.new_client_order_id(order_data["symbol"], order_data["action"]))
        reserved = self.db_manager.reserve_order_intent(self.account_id, client_id, {**order_data, "client_order_id": client_id})
        return {**order_data, "client_order_id": client_id, "intent": reserved}

    async def _cached_intent(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        if self.redis_cache is None:
            return None
        try:
            value = await self.redis_cache.get_state(f"order_intent_{client_order_id}")
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    async def _cache_intent(self, intent: Dict[str, Any]) -> None:
        if self.redis_cache is None:
            return
        try:
            await self.redis_cache.set_state(f"order_intent_{intent['client_order_id']}", intent)
        except Exception:
            logger.warning("Não foi possível cachear a intenção %s", intent.get("client_order_id"))

    async def submit_with_retry(
        self,
        order_data: Dict[str, Any],
        send: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        """Envia uma intenção com o mesmo clientOrderId e backoff exponencial."""
        prepared = self.reserve(order_data, client_order_id)
        client_id = prepared["client_order_id"]
        existing = self.db_manager.get_order_intent(client_id) or await self._cached_intent(client_id)
        if existing and existing.get("status") in {"submitted", "partially_filled", "filled"}:
            return {"status": "idempotent_reuse", "client_order_id": client_id, "intent": existing}

        last_error = "falha desconhecida"
        for attempt in range(1, self.max_attempts + 1):
            self.db_manager.update_order_intent(client_id, status="submitted", attempts=attempt, last_error=None)
            try:
                result = await send({**prepared, "client_order_id": client_id})
                result = dict(result or {})
                status = str(result.get("status", "error")).lower()
                if status in {"success", "filled", "partially_filled", "pending", "open"}:
                    exchange_id = result.get("order_id") or result.get("exchange_order_id")
                    intent = self.db_manager.update_order_intent(
                        client_id,
                        status="filled" if status == "success" and result.get("filled_quantity") else status,
                        exchange_order_id=str(exchange_id) if exchange_id is not None else None,
                        attempts=attempt,
                        payload_json=result,
                    )
                    await self._cache_intent(intent or {"client_order_id": client_id, "status": status, **result})
                    return {**result, "client_order_id": client_id, "intent": intent}
                last_error = str(result.get("reason") or result.get("error") or "adapter rejeitou a ordem")
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Falha no envio idempotente %s tentativa %d/%d: %s", client_id, attempt, self.max_attempts, exc)
            self.db_manager.update_order_intent(client_id, status="retrying" if attempt < self.max_attempts else "failed", attempts=attempt, last_error=last_error)
            if attempt < self.max_attempts:
                await asyncio.sleep(min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1))))
        return {"status": "error", "client_order_id": client_id, "reason": last_error, "attempts": self.max_attempts}

    async def _call_optional(self, name: str, default: Any) -> Any:
        method = getattr(self.exchange_connector, name, None)
        if method is None:
            return default
        value = await method()
        return value

    async def reconcile(self) -> Dict[str, Any]:
        """Compara ordens abertas e posições remotas com o estado persistido."""
        try:
            remote_orders = await self._call_optional("get_open_orders", [])
            remote_positions = await self._call_optional("get_positions", [])
            if not isinstance(remote_orders, list):
                remote_orders = list(remote_orders or [])
            if not isinstance(remote_positions, list):
                remote_positions = list(remote_positions or [])
            local_intents = self.db_manager.list_open_order_intents(self.account_id)
            local_positions = self.db_manager.get_open_runtime_positions(self.account_id)
            remote_ids = {str(item.get("client_order_id")) for item in remote_orders if item.get("client_order_id")}
            local_ids = {str(item.get("client_order_id")) for item in local_intents if item.get("client_order_id")}
            payload = {
                "open_orders_count": len(remote_orders),
                "positions_count": len(remote_positions),
                "remote_orders": remote_orders,
                "remote_positions": remote_positions,
                "untracked_remote_client_order_ids": sorted(remote_ids - local_ids),
                "local_intents_without_remote_order": sorted(local_ids - remote_ids),
                "local_positions": [self._position_dict(row) for row in local_positions],
            }
            status = "ok" if not payload["untracked_remote_client_order_ids"] else "attention"
            snapshot = self.db_manager.create_reconciliation_snapshot(self.account_id, status, payload)
            return {"status": status, **snapshot}
        except Exception as exc:
            self.db_manager.create_reconciliation_snapshot(self.account_id, "error", {"error": str(exc)})
            raise ReconciliationError(str(exc)) from exc

    @staticmethod
    def _position_dict(position: Any) -> Dict[str, Any]:
        return {
            "symbol": getattr(position, "symbol", None),
            "action": getattr(position, "action", None),
            "quantity": float(getattr(position, "quantity", 0.0) or 0.0),
            "entry_price": float(getattr(position, "entry_price", 0.0) or 0.0),
            "order_id": getattr(position, "order_id", None),
        }

    async def sync_positions(self) -> Dict[str, Any]:
        """Calcula a diferença entre posições esperadas e posições informadas."""
        remote = await self._call_optional("get_positions", [])
        remote = list(remote or []) if isinstance(remote, Iterable) else []
        local = self.db_manager.get_open_runtime_positions(self.account_id)
        local_by_symbol = {str(row.symbol): self._position_dict(row) for row in local}
        remote_by_symbol = {str(row.get("symbol")): dict(row) for row in remote if isinstance(row, dict) and row.get("symbol")}
        symbols = sorted(set(local_by_symbol) | set(remote_by_symbol))
        differences = []
        for symbol in symbols:
            expected = local_by_symbol.get(symbol, {})
            observed = remote_by_symbol.get(symbol, {})
            if abs(float(expected.get("quantity", 0.0)) - float(observed.get("quantity", 0.0))) > 1e-12 or expected.get("action") != observed.get("action"):
                differences.append({"symbol": symbol, "expected": expected, "observed": observed})
        status = "ok" if not differences else "attention"
        payload = {"positions_count": len(remote_by_symbol), "open_orders_count": 0, "expected": local_by_symbol, "observed": remote_by_symbol, "differences": differences}
        self.db_manager.create_reconciliation_snapshot(self.account_id, status, payload)
        return {"status": status, **payload}
