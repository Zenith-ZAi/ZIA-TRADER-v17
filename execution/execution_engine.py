import logging
import asyncio
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class ExecutionEngine:
    """Motor de execução de ordens com gerenciamento de posições."""

    def __init__(self):
        self.active_orders = {}
        self.closed_orders = []
        self.pnl_tracker = {}

    async def execute_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ordem validada pelo RiskAI."""
        try:
            order_id = f"ORD_{datetime.now().timestamp()}"
            symbol = order_data.get("symbol")
            action = order_data.get("action")
            quantity = order_data.get("quantity", 0)
            stop_loss = order_data.get("stop_loss", 0)
            take_profit = order_data.get("take_profit", 0)

            # Registrar a ordem ativa
            self.active_orders[order_id] = {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_time": datetime.now().isoformat(),
                "status": "open"
            }

            logger.info(f"✅ Ordem executada: {order_id} | {symbol} {action} {quantity} | SL: {stop_loss} | TP: {take_profit}")

            return {
                "status": "success",
                "order_id": order_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Erro ao executar ordem: {e}")
            return {
                "status": "error",
                "reason": str(e)
            }

    async def close_order(self, order_id: str, exit_price: float) -> Dict[str, Any]:
        """Fecha uma ordem aberta e calcula o PnL."""
        if order_id not in self.active_orders:
            logger.error(f"Ordem {order_id} não encontrada.")
            return {"status": "error", "reason": "Ordem não encontrada"}

        try:
            order = self.active_orders.pop(order_id)
            order["exit_price"] = exit_price
            order["exit_time"] = datetime.now().isoformat()
            order["status"] = "closed"

            # Calcular PnL (simplificado)
            pnl = (exit_price - order.get("entry_price", 0)) * order["quantity"]
            if order["action"] == "sell":
                pnl = -pnl

            order["pnl"] = pnl

            self.closed_orders.append(order)
            self.pnl_tracker[order_id] = pnl

            logger.info(f"✅ Ordem fechada: {order_id} | PnL: {pnl:.2f}")

            return {
                "status": "success",
                "order_id": order_id,
                "pnl": pnl,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ Erro ao fechar ordem: {e}")
            return {"status": "error", "reason": str(e)}

    def get_active_orders(self) -> Dict[str, Any]:
        """Retorna todas as ordens ativas."""
        return self.active_orders

    def get_closed_orders(self) -> list:
        """Retorna todas as ordens fechadas."""
        return self.closed_orders

    def get_total_pnl(self) -> float:
        """Calcula o PnL total."""
        return sum(self.pnl_tracker.values())

    def get_win_rate(self) -> float:
        """Calcula a taxa de vitória (% de trades lucrativos)."""
        if not self.closed_orders:
            return 0.0
        winning_trades = sum(1 for order in self.closed_orders if order.get("pnl", 0) > 0)
        return (winning_trades / len(self.closed_orders)) * 100
