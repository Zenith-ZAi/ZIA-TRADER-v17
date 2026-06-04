from typing import Dict, Any
from config.settings import settings

class RiskAI:
    """Módulo de IA para gerenciamento de risco e validação de ordens."""
    def __init__(self):
        self.max_risk_per_trade = settings.MAX_RISK_PER_TRADE
        self.daily_loss_limit = 0.05  # 5% do capital total

    def validate_order(self, order_data: Dict[str, Any], account_balance: float) -> Dict[str, Any]:
        """Valida se uma ordem está dentro dos parâmetros de risco."""
        symbol = order_data.get("symbol")
        action = order_data.get("action")
        confidence = order_data.get("confidence", 0.0)
        
        # 1. Verificação de Confiança Mínima
        if confidence < 0.7:
            return {"valid": False, "reason": f"Confiança insuficiente: {confidence:.2f}"}
            
        # 2. Cálculo de Tamanho de Posição (Exemplo: Critério de Kelly ou Risco Fixo)
        risk_amount = account_balance * self.max_risk_per_trade
        entry_price = order_data.get("price", 0.0)
        
        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}
            
        # 3. Definição de Stop Loss e Take Profit Dinâmicos
        stop_loss_pct = 0.02  # 2% fixo para o exemplo
        take_profit_pct = 0.05 # 5% fixo para o exemplo
        
        stop_loss = entry_price * (1 - stop_loss_pct) if action == "buy" else entry_price * (1 + stop_loss_pct)
        take_profit = entry_price * (1 + take_profit_pct) if action == "buy" else entry_price * (1 - take_profit_pct)
        
        # 4. Verificação de Limite de Perda Diária (Simulado)
        # Em produção, buscaríamos o PnL diário do banco de dados
        daily_pnl = 0.0
        if daily_pnl < -self.daily_loss_limit * account_balance:
            return {"valid": False, "reason": "Limite de perda diária atingido."}
            
        return {
            "valid": True,
            "symbol": symbol,
            "action": action,
            "quantity": risk_amount / (entry_price * stop_loss_pct),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount
        }

risk_ai = RiskAI()
