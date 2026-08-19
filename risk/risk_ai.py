"""Validação de risco independente da execução de ordens."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from config.settings import Settings
from database_manager import DatabaseManager


class RiskAI:
    """Módulo de risco determinístico e auditável."""

    def __init__(self, settings: Settings, db_manager: DatabaseManager):
        self.settings = settings
        self.db_manager = db_manager
        self.account_id = "default_account"
        self.max_risk_per_trade = float(settings.MAX_RISK_PER_TRADE)
        self.daily_loss_limit = float(settings.DAILY_LOSS_LIMIT_PERCENT)

    def analyze_volume_flow(self, historical_data: Any) -> Dict[str, Any]:
        """Identifica volume anormal e sua direção, sem afirmar causalidade."""
        try:
            if historical_data is None or "volume" not in historical_data.columns:
                return {"trend": "neutral", "anomaly": False, "z_score": 0.0}
            volumes = historical_data["volume"].astype(float).dropna()
            if len(volumes) < 20:
                return {"trend": "neutral", "anomaly": False, "z_score": 0.0}
            baseline = volumes.iloc[:-1].tail(20)
            std = float(baseline.std(ddof=0))
            z_score = float((volumes.iloc[-1] - baseline.mean()) / std) if std > 0 else 0.0
            close_change = float(historical_data["close"].iloc[-1] - historical_data["close"].iloc[-2]) if "close" in historical_data.columns and len(historical_data) > 1 else 0.0
            trend = "bullish" if z_score >= 2 and close_change > 0 else "bearish" if z_score >= 2 and close_change < 0 else "neutral"
            return {"trend": trend, "anomaly": abs(z_score) >= 2, "z_score": z_score}
        except Exception:
            return {"trend": "neutral", "anomaly": False, "z_score": 0.0}

    def _exposure(self) -> tuple[float, Dict[str, float]]:
        """Obtém exposição atual; falhas de leitura bloqueiam apenas a expansão."""
        try:
            positions = self.db_manager.get_open_positions(self.account_id)
        except Exception:
            return float("inf"), {}
        total = 0.0
        by_symbol: Dict[str, float] = {}
        for position in positions:
            notional = abs(float(position.quantity) * float(position.current_price))
            total += notional
            by_symbol[position.symbol] = by_symbol.get(position.symbol, 0.0) + notional
        return total, by_symbol

    @staticmethod
    def quote_equivalent_balance(balances: Dict[str, float], symbol: str, reference_price: float) -> float:
        """Estima capital em moeda de cotação sem contar ativos não conversíveis."""
        try:
            base, quote = symbol.replace("-", "/").split("/", 1)
            price = float(reference_price)
            stable_assets = {quote, "USDT", "USDC", "BUSD", "FDUSD"}
            total = sum(float(balances.get(asset, 0.0)) for asset in stable_assets)
            total += float(balances.get(base, 0.0)) * price
            return max(0.0, total)
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def validate_exit(
        self,
        position: Dict[str, Any],
        price: float,
        market_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Valida somente o fechamento de uma posição já existente."""
        action = str(position.get("action") or "").lower()
        symbol = str(position.get("symbol") or "").strip()
        try:
            quantity = float(position.get("quantity", 0.0))
            price = float(price)
        except (TypeError, ValueError):
            return {"valid": False, "reason": "Campos de saída inválidos."}
        if action not in {"buy", "sell"} or not symbol or quantity <= 0 or price <= 0:
            return {"valid": False, "reason": "Posição ou preço de saída inválidos."}
        balances = (market_context or {}).get("exchange_balances", {})
        if isinstance(balances, dict) and balances:
            try:
                base_asset = symbol.replace("-", "/").split("/", 1)[0]
                available = float(balances.get(base_asset, 0.0))
                if action == "buy" and available + 1e-12 < quantity:
                    return {"valid": False, "reason": "Saldo base insuficiente para fechar a posição."}
            except (TypeError, ValueError, IndexError):
                return {"valid": False, "reason": "Saldo da exchange inválido para a saída."}
        return {
            "valid": True,
            "symbol": symbol,
            "action": "sell" if action == "buy" else "buy",
            "quantity": quantity,
            "price": price,
            "exit_reason": str(position.get("exit_reason") or "policy"),
        }

    def validate_order(
        self,
        order_data: Dict[str, Any],
        account_balance: float,
        market_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Valida ordem, calcula quantidade e retorna motivo explícito em rejeições."""
        symbol = str(order_data.get("symbol") or "").strip()
        action = str(order_data.get("action") or "").lower()
        try:
            confidence = float(order_data.get("confidence", 0.0))
            entry_price = float(order_data.get("price", 0.0))
            account_balance = float(account_balance)
        except (TypeError, ValueError):
            return {"valid": False, "reason": "Campos numéricos inválidos."}

        if not symbol or action not in {"buy", "sell"}:
            return {"valid": False, "reason": "Símbolo ou ação inválidos."}
        if account_balance <= 0:
            return {"valid": False, "reason": "Saldo da conta inválido."}
        if confidence < float(self.settings.MIN_CONFIDENCE_THRESHOLD):
            return {"valid": False, "reason": f"Confiança insuficiente: {confidence:.2f}"}
        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}

        daily_pnl_obj = self.db_manager.get_daily_pnl(
            self.account_id,
            datetime.now(timezone.utc).replace(tzinfo=None),
        )
        daily_pnl = float(daily_pnl_obj.pnl) if daily_pnl_obj else 0.0
        if daily_pnl < -self.daily_loss_limit * account_balance:
            return {"valid": False, "reason": "Limite de perda diária atingido."}

        stop_loss_pct = float(self.settings.STOP_LOSS_PCT)
        take_profit_pct = float(self.settings.TAKE_PROFIT_PCT)
        risk_amount = account_balance * self.max_risk_per_trade
        unit_risk = entry_price * stop_loss_pct
        if risk_amount <= 0 or unit_risk <= 0:
            return {"valid": False, "reason": "Parâmetros de risco inválidos."}

        risk_quantity = risk_amount / unit_risk
        max_symbol_notional = account_balance * float(self.settings.MAX_EXPOSURE_PER_SYMBOL)
        max_total_notional = account_balance * float(self.settings.MAX_TOTAL_EXPOSURE)
        total_exposure, exposure_by_symbol = self._exposure()
        symbol_exposure = exposure_by_symbol.get(symbol, 0.0)
        if total_exposure == float("inf"):
            return {"valid": False, "reason": "Não foi possível confirmar a exposição atual."}
        available_symbol_notional = max(0.0, max_symbol_notional - symbol_exposure)
        available_total_notional = max(0.0, max_total_notional - total_exposure)
        available_notional = min(available_symbol_notional, available_total_notional)
        quantity = min(risk_quantity, available_notional / entry_price)
        proposed_notional = quantity * entry_price
        if quantity <= 0 or proposed_notional <= 0:
            if available_symbol_notional <= 0:
                return {"valid": False, "reason": "Limite de exposição por símbolo excedido."}
            return {"valid": False, "reason": "Limite de exposição total excedido."}

        exchange_balances = (market_context or {}).get("exchange_balances", {})
        if isinstance(exchange_balances, dict) and exchange_balances:
            try:
                base_asset, quote_asset = symbol.replace("-", "/").split("/", 1)
                available_asset = float(exchange_balances.get(quote_asset if action == "buy" else base_asset, 0.0))
                required_asset = proposed_notional if action == "buy" else quantity
                if available_asset < required_asset:
                    return {"valid": False, "reason": "Saldo disponível na exchange insuficiente para a ordem."}
            except (TypeError, ValueError):
                return {"valid": False, "reason": "Saldo da exchange inválido para o símbolo."}

        stop_loss = entry_price * (1 - stop_loss_pct) if action == "buy" else entry_price * (1 + stop_loss_pct)
        take_profit = entry_price * (1 + take_profit_pct) if action == "buy" else entry_price * (1 - take_profit_pct)
        return {
            "valid": True,
            "symbol": symbol,
            "action": action,
            "quantity": float(quantity),
            "price": entry_price,
            "confidence": confidence,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount,
            "projected_notional": proposed_notional,
        }
