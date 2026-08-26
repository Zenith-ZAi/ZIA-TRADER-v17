"""Gerenciamento de proteção pós-fill para paper, sandbox e adapters homologados."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)


class OCOManagerError(RuntimeError):
    """Erro no ciclo de proteção da posição."""


class OCOManager:
    """Anexa stop e alvo a uma posição já preenchida.

    O adapter pode fornecer ``place_oco_orders`` para uma operação nativa. Sem
    esse método, são enviadas duas ordens de proteção independentes, cada uma
    persistida com ``reduce_only`` e vinculada ao ``parent_client_order_id``.
    Em produção, o reconciler deve confirmar o cancelamento da proteção oposta
    após o primeiro fill.
    """

    def __init__(self, exchange_connector: Any, db_manager: Any | None = None, account_id: str = "default_account"):
        self.exchange_connector = exchange_connector
        self.db_manager = db_manager
        self.account_id = account_id

    @staticmethod
    def _client_id(parent: str, kind: str) -> str:
        return f"zia_{kind}_{parent[-16:]}_{uuid.uuid4().hex[:8]}"

    async def _place_one(self, protection: Dict[str, Any]) -> Dict[str, Any]:
        native = getattr(self.exchange_connector, "place_protection_order", None)
        if native is not None:
            return dict(await native(protection))
        return dict(await self.exchange_connector.place_order(
            protection["symbol"],
            protection["action"],
            protection["order_type"],
            protection["quantity"],
            protection.get("limit_price") or protection.get("stop_price"),
        ))

    async def attach_protection(
        self,
        fill: Dict[str, Any],
        stop_loss: float,
        take_profit: float,
        use_native_oco: bool = True,
    ) -> Dict[str, Any]:
        symbol = str(fill.get("symbol") or "")
        parent = str(fill.get("client_order_id") or fill.get("order_id") or "")
        action = str(fill.get("action") or "").lower()
        quantity = float(fill.get("filled_quantity") or fill.get("quantity") or 0.0)
        if not symbol or action not in {"buy", "sell"} or quantity <= 0 or stop_loss <= 0 or take_profit <= 0:
            raise OCOManagerError("fill ou preços de proteção inválidos")
        exit_action = "sell" if action == "buy" else "buy"
        common = {
            "symbol": symbol,
            "action": exit_action,
            "quantity": quantity,
            "reduce_only": True,
            "parent_client_order_id": parent,
        }
        native = getattr(self.exchange_connector, "place_oco_orders", None)
        if native is not None and use_native_oco:
            result = dict(await native({**common, "stop_price": float(stop_loss), "take_profit": float(take_profit)}))
            if str(result.get("status", "")).lower() not in {"unsupported", "error"}:
                protections = result.get("protections", [])
                for item in protections:
                    if self.db_manager is not None:
                        self.db_manager.upsert_protection_order(self.account_id, {**common, **item})
                return {"status": result.get("status", "success"), "mode": "native_oco", "protections": protections, "parent_client_order_id": parent}

        protections = [
            {
                **common,
                "client_order_id": self._client_id(parent, "sl"),
                "order_type": "stop_loss_limit",
                "stop_price": float(stop_loss),
                "limit_price": float(stop_loss),
                "status": "pending",
            },
            {
                **common,
                "client_order_id": self._client_id(parent, "tp"),
                "order_type": "take_profit_limit",
                "stop_price": float(take_profit),
                "limit_price": float(take_profit),
                "status": "pending",
            },
        ]
        results = []
        for protection in protections:
            if self.db_manager is not None:
                self.db_manager.upsert_protection_order(self.account_id, protection)
            try:
                result = await self._place_one(protection)
                result = {**protection, **result, "status": result.get("status", "success")}
                if self.db_manager is not None:
                    self.db_manager.update_protection_order(
                        protection["client_order_id"],
                        exchange_order_id=result.get("order_id"),
                        status="open" if result.get("status") == "success" else str(result.get("status")),
                    )
                results.append(result)
            except Exception as exc:
                logger.error("Falha ao anexar proteção %s: %s", protection["client_order_id"], exc)
                if self.db_manager is not None:
                    self.db_manager.update_protection_order(protection["client_order_id"], status="error")
                results.append({**protection, "status": "error", "reason": str(exc)})
        status = "success" if all(item.get("status") == "success" for item in results) else "partial" if any(item.get("status") == "success" for item in results) else "error"
        return {"status": status, "mode": "separate_orders", "protections": results, "parent_client_order_id": parent}

    async def cancel_for_parent(self, parent_client_order_id: str) -> Dict[str, Any]:
        protections = self.db_manager.list_active_protection_orders(self.account_id, parent_client_order_id) if self.db_manager is not None else []
        results = []
        for item in protections:
            order_id = item.get("exchange_order_id")
            try:
                if order_id:
                    result = await self.exchange_connector.cancel_order(order_id)
                else:
                    result = {"status": "cancelled", "order_id": item.get("client_order_id")}
                if self.db_manager is not None:
                    self.db_manager.update_protection_order(item["client_order_id"], status="canceled")
                results.append(result)
            except Exception as exc:
                results.append({"status": "error", "order_id": order_id, "reason": str(exc)})
        return {"parent_client_order_id": parent_client_order_id, "cancelled": results, "status": "success" if all(item.get("status") != "error" for item in results) else "partial"}
