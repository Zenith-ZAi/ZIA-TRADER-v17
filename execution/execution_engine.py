import logging
from typing import Any, Dict, Optional

from config.settings import Settings
from database import MarketType
from infra.redis_cache import RedisCache
from execution.exchange_connector import ExchangeConnector
from core.reconciliation import OrderReconciler
from execution.oco_manager import OCOManager

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Motor de execução de ordens para interagir com exchanges.

    Após uma entrada preenchida, mantém um estado rico no cache e uma posição
    auditável no banco. Após uma saída, remove o cache e fecha a posição aberta.
    A persistência é best-effort: uma falha de banco não transforma uma ordem já
    preenchida em uma ordem ficticiamente rejeitada.
    """

    def __init__(
        self,
        settings: Settings,
        exchange_connector: ExchangeConnector,
        redis_cache: RedisCache,
        db_manager: Any | None = None,
        account_id: str = "default_account",
    ):
        self.settings = settings
        self.exchange_connector = exchange_connector
        self.redis_cache = redis_cache
        self.db_manager = db_manager
        self.account_id = account_id
        self.is_connected = True  # Assume connected via ExchangeConnector
        self.reconciler = None
        if self.db_manager is not None and hasattr(self.db_manager, "reserve_order_intent"):
            self.reconciler = OrderReconciler(
                self.db_manager,
                self.exchange_connector,
                self.redis_cache,
                account_id=self.account_id,
                max_attempts=int(getattr(settings, "RECONCILIATION_MAX_ATTEMPTS", 3)),
                base_delay_seconds=float(getattr(settings, "RECONCILIATION_BASE_DELAY_SECONDS", 0.25)),
                max_delay_seconds=float(getattr(settings, "RECONCILIATION_MAX_DELAY_SECONDS", 4.0)),
            )
        self.oco_manager = OCOManager(self.exchange_connector, self.db_manager, self.account_id) if bool(getattr(settings, "OCO_ENABLED", False)) and hasattr(self.exchange_connector, "place_protection_order") else None

    @staticmethod
    def _market_type(order_data: Dict[str, Any]) -> MarketType:
        raw_market_type = order_data.get("market_type", MarketType.CRYPTO)
        if isinstance(raw_market_type, MarketType):
            return raw_market_type
        try:
            return MarketType(str(raw_market_type).lower())
        except ValueError:
            return MarketType.CRYPTO

    async def _persist_entry(
        self,
        order_data: Dict[str, Any],
        order_id: str,
        filled_price: float,
        filled_quantity: float,
    ) -> None:
        symbol = str(order_data["symbol"])
        position_state = {
            "symbol": symbol,
            "action": str(order_data["action"]).lower(),
            "quantity": filled_quantity,
            "entry_price": filled_price,
            "stop_loss": order_data.get("stop_loss"),
            "take_profit": order_data.get("take_profit"),
            "breakeven_trigger": order_data.get("breakeven_trigger"),
            "status": "open",
            "order_id": order_id,
        }
        await self.redis_cache.set_state(f"position_{symbol}", position_state)
        if self.db_manager is not None:
            try:
                self.db_manager.upsert_runtime_position(self.account_id, position_state)
                self.db_manager.create_position(
                    self.account_id,
                    symbol,
                    self._market_type(order_data),
                    filled_quantity,
                    filled_price,
                    filled_price,
                )
            except Exception as exc:
                logger.error("Falha ao persistir posição preenchida de %s: %s", symbol, exc)

    async def _persist_exit(self, symbol: str) -> None:
        await self.redis_cache.delete_state(f"position_{symbol}")
        if self.db_manager is not None:
            try:
                self.db_manager.close_runtime_position(self.account_id, symbol)
                self.db_manager.close_position(self.account_id, symbol)
            except Exception as exc:
                logger.error("Falha ao fechar posição persistida de %s: %s", symbol, exc)

    async def execute_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem de mercado ou limite na exchange."""
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        quantity = order_data.get("quantity", 0.0)

        if not symbol or not action or quantity <= 0:
            return {"status": "error", "reason": "Dados de ordem inválidos."}

        client_order_id = str(order_data.get("client_order_id") or "")
        if not client_order_id and self.reconciler is not None:
            client_order_id = self.reconciler.new_client_order_id(str(symbol), str(action))
            order_data = {**order_data, "client_order_id": client_order_id}

        async def send(prepared: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return await self.exchange_connector.place_order(
                    symbol,
                    action,
                    "market",
                    quantity,
                    order_data.get("price"),
                    client_order_id=prepared.get("client_order_id"),
                )
            except TypeError:
                return await self.exchange_connector.place_order(symbol, action, "market", quantity, order_data.get("price"))

        try:
            if self.reconciler is not None:
                order_result = await self.reconciler.submit_with_retry(order_data, send, client_order_id=client_order_id or None)
                if order_result.get("status") == "idempotent_reuse":
                    return {"status": "success", "client_order_id": client_order_id, **order_result}
            else:
                order_result = await send({"client_order_id": client_order_id})
            if str(order_result.get("status", "")).lower() in {"failed", "error"}:
                raise Exception(order_result.get("error") or order_result.get("reason") or "ordem rejeitada")
            order_id = order_result["order_id"]
            filled_price = float(order_result.get("filled_price") or order_data.get("price") or 0.0)
            filled_quantity = float(order_result.get("filled_quantity") or quantity)
            if filled_price <= 0 or filled_quantity <= 0:
                return {"status": "error", "reason": "Execução sem preço ou quantidade preenchida válida."}

            if order_data.get("exit_reason"):
                await self._persist_exit(str(symbol))
            else:
                await self._persist_entry(order_data, order_id, filled_price, filled_quantity)
                if self.oco_manager is not None and bool(getattr(self.settings, "OCO_ENABLED", False)):
                    stop_loss = order_data.get("stop_loss")
                    take_profit = order_data.get("take_profit")
                    if stop_loss and take_profit:
                        protection = await self.oco_manager.attach_protection(
                            {**order_data, **order_result, "client_order_id": client_order_id or order_result.get("client_order_id")},
                            float(stop_loss),
                            float(take_profit),
                        )
                        order_result = {**order_result, "protection": protection}

            return {
                "status": "success",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "filled_price": filled_price,
                "filled_quantity": filled_quantity,
                "commission": order_result.get("commission", 0.0),
            }
        except Exception as e:
            logger.error(f"Erro ao executar ordem para {symbol}: {e}")
            return {"status": "error", "reason": str(e)}
