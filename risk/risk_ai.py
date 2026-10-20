"""Validação de risco independente da execução de ordens."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from config.settings import Settings
from database_manager import DatabaseManager
from risk.adaptive_kelly import AdaptiveKellySizer


class RiskAI:
    """Módulo de risco determinístico e auditável."""

    def __init__(self, settings: Settings, db_manager: DatabaseManager):
        self.settings = settings
        self.db_manager = db_manager
        self.account_id = "default_account"
        self.max_risk_per_trade = float(settings.MAX_RISK_PER_TRADE)
        self.daily_loss_limit = float(settings.DAILY_LOSS_LIMIT_PERCENT)
        self.adaptive_kelly = AdaptiveKellySizer(
            fraction=float(getattr(settings, "ADAPTIVE_KELLY_FRACTION", 0.25)),
            target_volatility=float(getattr(settings, "KELLY_TARGET_VOLATILITY", 0.02)),
            max_risk_fraction=float(getattr(settings, "KELLY_MAX_RISK_FRACTION", self.max_risk_per_trade)),
        )

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

    @staticmethod
    def _parse_utc(value: Any) -> datetime | None:
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    def _period_loss_status(self, execution_source: str, now: datetime | None = None) -> Dict[str, Any]:
        """Valida limites diário/semanal/mensal sem confiar em tabelas de P&L incompletas."""
        if execution_source not in {"ai", "manual"}:
            return {"required": False, "allowed": True, "status": "not_execution_path"}
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            daily_limit = float(self.settings.DAILY_LOSS_LIMIT_PERCENT)
            weekly_limit = float(self.settings.WEEKLY_LOSS_LIMIT_PERCENT)
            monthly_limit = float(self.settings.MONTHLY_LOSS_LIMIT_PERCENT)
        except (TypeError, ValueError, AttributeError):
            return {"required": True, "allowed": False, "status": "invalid_limits"}
        if any(not math.isfinite(value) or value <= 0.0 or value > 1.0 for value in (daily_limit, weekly_limit, monthly_limit)):
            return {"required": True, "allowed": False, "status": "invalid_limits"}
        try:
            snapshot = self.db_manager.get_verified_risk_periods(self.account_id, now_utc)
        except Exception:
            snapshot = None
        if not isinstance(snapshot, dict):
            return {
                "required": True,
                "allowed": False,
                "status": "period_ledger_unavailable",
                "reason": "Ledger verificável de P&L diário/semanal/mensal indisponível; novas entradas bloqueadas.",
            }

        updated_at = self._parse_utc(snapshot.get("updated_at"))
        max_age = max(1.0, float(getattr(self.settings, "RISK_PERIOD_SNAPSHOT_MAX_AGE_SECONDS", 300)))
        if (
            snapshot.get("account_id") != self.account_id
            or snapshot.get("source") != "equity_ledger_v1"
            or snapshot.get("complete") is not True
            or snapshot.get("fees_included") is not True
            or snapshot.get("funding_included") is not True
            or snapshot.get("external_flows_adjusted") is not True
            or snapshot.get("ledger_consistent") is not True
            or updated_at is None
            or (now_utc - updated_at).total_seconds() < -1.0
            or (now_utc - updated_at).total_seconds() > max_age
        ):
            return {
                "required": True,
                "allowed": False,
                "status": "period_ledger_unverified",
                "reason": "Snapshot diário/semanal/mensal incompleto, obsoleto ou sem proveniência exigida; novas entradas bloqueadas.",
            }

        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = (now_utc - timedelta(days=now_utc.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        checks = []
        for name, limit, expected_start in (
            ("daily", daily_limit, day_start),
            ("weekly", weekly_limit, week_start),
            ("monthly", monthly_limit, month_start),
        ):
            period = snapshot.get(name)
            if not isinstance(period, dict) or self._parse_utc(period.get("period_start")) != expected_start:
                return {
                    "required": True,
                    "allowed": False,
                    "status": f"{name}_period_mismatch",
                    "reason": f"Período {name} não corresponde ao calendário UTC atual; novas entradas bloqueadas.",
                }
            try:
                starting_equity = float(period.get("starting_equity"))
                realized_pnl = float(period.get("realized_pnl"))
                unrealized_pnl = float(period.get("unrealized_pnl"))
            except (TypeError, ValueError):
                starting_equity = realized_pnl = unrealized_pnl = float("nan")
            if (
                not all(math.isfinite(value) for value in (starting_equity, realized_pnl, unrealized_pnl))
                or starting_equity <= 0.0
            ):
                return {
                    "required": True,
                    "allowed": False,
                    "status": f"{name}_metrics_invalid",
                    "reason": f"Métricas de risco {name} inválidas; novas entradas bloqueadas.",
                }
            pnl = realized_pnl + unrealized_pnl
            loss_fraction = max(0.0, -pnl / starting_equity)
            checks.append({"period": name, "loss_fraction": loss_fraction, "limit": limit, "pnl": pnl})
            if loss_fraction >= limit:
                return {
                    "required": True,
                    "allowed": False,
                    "status": f"{name}_loss_limit_reached",
                    "checks": checks,
                    "reason": f"Limite de perda {name} atingido; novas entradas bloqueadas.",
                }
        return {"required": True, "allowed": True, "status": "within_limits", "checks": checks}

    def _verified_trade_returns(self, market_context: Dict[str, Any] | None = None) -> tuple[list[float], str]:
        """Aceita amostras somente do contrato persistente, nunca do chamador."""
        del market_context  # contexto de runtime não é evidência de persistência
        try:
            snapshot = self.db_manager.get_verified_trade_returns(self.account_id, limit=100)
        except Exception:
            snapshot = None
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("account_id") != self.account_id
            or snapshot.get("source") != "closed_execution_ledger_v1"
            or snapshot.get("complete") is not True
            or snapshot.get("fees_included") is not True
            or snapshot.get("funding_included") is not True
            or snapshot.get("external_flows_adjusted") is not True
        ):
            return [], "unverified_or_missing_source"
        samples = snapshot.get("returns")
        if not isinstance(samples, (list, tuple)):
            return [], "unverified_or_missing_source"
        now = datetime.now(timezone.utc)
        max_age_days = max(1.0, float(getattr(self.settings, "KELLY_TRADE_SAMPLE_MAX_AGE_DAYS", 365)))
        parsed: list[tuple[datetime, str, float]] = []
        seen_ids: set[str] = set()
        for sample in samples:
            if not isinstance(sample, dict):
                return [], "invalid_sample"
            closed_at = RiskAI._parse_utc(sample.get("closed_at"))
            execution_id = str(sample.get("execution_id") or "")
            try:
                realized_return = float(sample.get("return_pct"))
            except (TypeError, ValueError):
                return [], "invalid_sample"
            if (
                closed_at is None
                or closed_at > now + timedelta(seconds=1)
                or (now - closed_at).total_seconds() > max_age_days * 86400
                or not execution_id
                or execution_id in seen_ids
                or not math.isfinite(realized_return)
            ):
                return [], "invalid_sample"
            seen_ids.add(execution_id)
            parsed.append((closed_at, execution_id, realized_return))
        if any(parsed[index][0] > parsed[index + 1][0] for index in range(len(parsed) - 1)):
            return [], "non_chronological_samples"
        if len(parsed) < 20:
            return [], "insufficient_history"
        return [sample[2] for sample in parsed], "verified"

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
        execution_source = str((market_context or {}).get("execution_source", "shadow")).lower()
        if execution_source != "manual" and confidence < float(self.settings.MIN_CONFIDENCE_THRESHOLD):
            return {"valid": False, "reason": f"Confiança insuficiente: {confidence:.2f}"}
        if entry_price <= 0:
            return {"valid": False, "reason": "Preço de entrada inválido."}

        period_risk = self._period_loss_status(execution_source)
        if not period_risk["allowed"]:
            return {"valid": False, "reason": period_risk.get("reason", "Verificação diário/semanal/mensal falhou."), "period_risk": period_risk}

        microstructure = (market_context or {}).get("microstructure") or {}
        if bool(getattr(self.settings, "MICROSTRUCTURE_GATE_ENABLED", True)) and microstructure and not microstructure.get("allowed", False):
            return {
                "valid": False,
                "reason": "; ".join(microstructure.get("reasons", ["microestrutura rejeitada"])),
                "microstructure": microstructure,
            }

        daily_pnl_obj = self.db_manager.get_daily_pnl(
            self.account_id,
            datetime.now(timezone.utc).replace(tzinfo=None),
        )
        daily_pnl = float(daily_pnl_obj.pnl) if daily_pnl_obj else 0.0
        if daily_pnl < -self.daily_loss_limit * account_balance:
            return {"valid": False, "reason": "Limite de perda diária atingido."}

        stop_loss_pct = float(self.settings.STOP_LOSS_PCT)
        take_profit_pct = float(self.settings.TAKE_PROFIT_PCT)
        adaptive_kelly = None
        trade_returns_status = "disabled_by_config"
        risk_fraction = self.max_risk_per_trade
        trade_returns: list[float] = []
        if bool(getattr(self.settings, "ADAPTIVE_KELLY_ENABLED", True)):
            trade_returns, trade_returns_status = self._verified_trade_returns(market_context)
        if bool(getattr(self.settings, "ADAPTIVE_KELLY_ENABLED", True)) and len(trade_returns) >= 20:
            reward_risk = take_profit_pct / max(stop_loss_pct, 1e-9)
            adaptive_kelly = self.adaptive_kelly.estimate(trade_returns, reward_risk=reward_risk)
            risk_fraction = min(risk_fraction, float(adaptive_kelly.get("risk_fraction", 0.0)))
            if risk_fraction <= 0.0:
                return {"valid": False, "reason": "Kelly adaptativo não identificou vantagem estatística suficiente.", "adaptive_kelly": adaptive_kelly, "adaptive_kelly_status": trade_returns_status}
        risk_amount = account_balance * risk_fraction
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
            "risk_fraction": risk_fraction,
            "projected_notional": proposed_notional,
            "microstructure": microstructure,
            "adaptive_kelly": adaptive_kelly,
            "adaptive_kelly_status": trade_returns_status,
            "period_risk": period_risk,
        }
