import logging
from typing import Dict, Any
from datetime import datetime

from database import close_trade_in_db

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Motor de execução de ordens com gerenciamento de posições."""

    def __init__(self):
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        self.closed_orders: list = []
        self.pnl_tracker: Dict[str, float] = {}

    async def execute_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem validada pelo RiskAI."""
        try:
            order_id = f"ORD_{datetime.now().timestamp()}"
            symbol = order_data.get("symbol")
            action = order_data.get("action")
            quantity = order_data.get("quantity", 0)
            price = order_data.get("price", 0)
            stop_loss = order_data.get("stop_loss", 0)
            take_profit = order_data.get("take_profit", 0)

            self.active_orders[order_id] = {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "entry_price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_time": datetime.now().isoformat(),
                "status": "open",
            }

            logger.info(
                "Ordem executada: %s | %s %s %s | SL: %s | TP: %s",
                order_id,
                symbol,
                action,
                quantity,
                stop_loss,
                take_profit,
            )

            return {
                "status": "success",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error("Erro ao executar ordem: %s", e)
            return {"status": "error", "reason": str(e)}

    async def close_order(self, order_id: str, exit_price: float) -> Dict[str, Any]:
        """Fecha uma ordem aberta e calcula o PnL."""
        if order_id not in self.active_orders:
            logger.error("Ordem %s não encontrada.", order_id)
            return {"status": "error", "reason": "Ordem não encontrada"}

        try:
            order = self.active_orders.pop(order_id)
            entry_price = order.get("entry_price", 0)
            order["exit_price"] = exit_price
            order["exit_time"] = datetime.now().isoformat()
            order["status"] = "closed"

            pnl = (exit_price - entry_price) * order["quantity"]
            if order["action"] == "sell":
                pnl = -pnl

            order["pnl"] = pnl

            self.closed_orders.append(order)
            self.pnl_tracker[order_id] = pnl

            # Persist to database
            await close_trade_in_db(order_id, exit_price, pnl)

            logger.info("Ordem fechada: %s | PnL: %.2f", order_id, pnl)

            return {
                "status": "success",
                "order_id": order_id,
                "pnl": pnl,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error("Erro ao fechar ordem: %s", e)
            return {"status": "error", "reason": str(e)}

    def get_active_orders(self) -> Dict[str, Any]:
        return self.active_orders

    def get_closed_orders(self) -> list:
        return self.closed_orders

    def get_total_pnl(self) -> float:
        return sum(self.pnl_tracker.values())

    def get_win_rate(self) -> float:
        if not self.closed_orders:
            return 0.0
        winning = sum(1 for o in self.closed_orders if o.get("pnl", 0) > 0)
        return (winning / len(self.closed_orders)) * 100
