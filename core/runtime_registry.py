"""Ponte entre as tabelas do console administrativo e o runtime de trading."""

from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from cli.db_models import AlgorithmConfig, StrategyConfig

logger = logging.getLogger(__name__)


class RuntimeConfigRegistry:
    def __init__(self, db_manager: Any):
        self.db_manager = db_manager
        self.last_profile: Dict[str, Any] = {}

    def _tables_available(self) -> bool:
        try:
            inspector = inspect(self.db_manager.engine)
            return inspector.has_table("strategy_configs") and inspector.has_table("algorithm_configs")
        except Exception as exc:
            logger.warning("Não foi possível inspecionar configurações do menu: %s", exc)
            return False

    def load_profile(self) -> Dict[str, Any]:
        if not self._tables_available():
            return {"source": "defaults", "strategy": None, "algorithm": None, "controlled": False}
        session = self.db_manager.SessionLocal()
        try:
            strategies = session.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True)).order_by(StrategyConfig.priority.desc(), StrategyConfig.weight.desc()).all()
            algorithms = session.query(AlgorithmConfig).filter(AlgorithmConfig.enabled.is_(True)).order_by(AlgorithmConfig.weight.desc(), AlgorithmConfig.confluence.desc()).all()
            strategy = strategies[0] if strategies else None
            algorithm = algorithms[0] if algorithms else None
            profile = {
                "source": "admin_menu",
                "controlled": bool(strategy or algorithm),
                "strategy": {
                    "id": strategy.id,
                    "name": strategy.name,
                    "priority": strategy.priority,
                    "weight": strategy.weight,
                    "timeframes": strategy.timeframes,
                    "stop_loss": strategy.stop_loss,
                    "take_profit": strategy.take_profit,
                    "trailing": strategy.trailing,
                    "params": strategy.params_json or {},
                } if strategy else None,
                "algorithm": {
                    "id": algorithm.id,
                    "name": algorithm.name,
                    "weight": algorithm.weight,
                    "confluence": algorithm.confluence,
                    "risk_management": algorithm.risk_management or {},
                    "indicators": algorithm.indicators or [],
                } if algorithm else None,
            }
            self.last_profile = profile
            return profile
        except Exception as exc:
            logger.warning("Configuração do menu indisponível; usando defaults: %s", exc)
            return {"source": "defaults", "strategy": None, "algorithm": None, "controlled": False, "error": str(exc)}
        finally:
            session.close()

    def apply_to_settings(self, settings: Any) -> Dict[str, Any]:
        profile = self.load_profile()
        strategy = profile.get("strategy") or {}
        algorithm = profile.get("algorithm") or {}
        if strategy:
            timeframes = str(strategy.get("timeframes") or "").strip()
            if timeframes:
                settings.ANALYSIS_TIMEFRAMES = timeframes
                parsed = [value.strip() for value in timeframes.split(",") if value.strip()]
                if parsed:
                    settings.TIMEFRAME = parsed[-1]
                    settings.MULTI_TIMEFRAME_ENABLED = len(parsed) > 1
            if strategy.get("stop_loss") is not None:
                settings.STOP_LOSS_PCT = float(strategy["stop_loss"])
            if strategy.get("take_profit") is not None:
                settings.TAKE_PROFIT_PCT = float(strategy["take_profit"])
        risk_management = algorithm.get("risk_management") or {}
        if risk_management.get("max_risk") is not None:
            settings.MAX_RISK_PER_TRADE = float(risk_management["max_risk"])
        if algorithm.get("confluence") is not None:
            settings.MIN_CONFIDENCE_THRESHOLD = max(
                float(settings.MIN_CONFIDENCE_THRESHOLD),
                float(algorithm["confluence"]),
            )
        return profile
