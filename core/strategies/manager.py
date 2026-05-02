import logging
from typing import Dict, Any, List
from config.settings import Settings

logger = logging.getLogger(__name__)

class StrategyManager:
    """Gerenciador de estratégias de trading."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.strategies = {}
        self._initialize_strategies()

    def _initialize_strategies(self):
        """Inicializa as estratégias disponíveis."""
        self.strategies = {
            "momentum": self._momentum_strategy,
            "mean_reversion": self._mean_reversion_strategy,
            "trend_following": self._trend_following_strategy,
            "arbitrage": self._arbitrage_strategy
        }
        logger.info(f"✅ {len(self.strategies)} estratégias carregadas.")

    def _momentum_strategy(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Estratégia de Momentum: Compra quando o preço está subindo forte."""
        price = market_data.get("price", 0)
        volume = market_data.get("volume", 0)
        rsi = market_data.get("rsi", 50)

        if rsi > 70 and volume > market_data.get("avg_volume", 0) * 1.5:
            return {"signal": "sell", "confidence": 0.8, "reason": "Momentum de venda forte"}
        elif rsi < 30 and volume > market_data.get("avg_volume", 0) * 1.5:
            return {"signal": "buy", "confidence": 0.8, "reason": "Momentum de compra forte"}
        else:
            return {"signal": "hold", "confidence": 0.5, "reason": "Sem sinal de momentum"}

    def _mean_reversion_strategy(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Estratégia de Mean Reversion: Compra quando o preço está muito baixo."""
        price = market_data.get("price", 0)
        sma_20 = market_data.get("sma_20", 0)
        std_dev = market_data.get("std_dev", 0)

        if price < sma_20 - (2 * std_dev):
            return {"signal": "buy", "confidence": 0.7, "reason": "Preço muito abaixo da média"}
        elif price > sma_20 + (2 * std_dev):
            return {"signal": "sell", "confidence": 0.7, "reason": "Preço muito acima da média"}
        else:
            return {"signal": "hold", "confidence": 0.5, "reason": "Preço próximo à média"}

    def _trend_following_strategy(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Estratégia de Trend Following: Segue a tendência do mercado."""
        sma_50 = market_data.get("sma_50", 0)
        sma_200 = market_data.get("sma_200", 0)
        price = market_data.get("price", 0)

        if sma_50 > sma_200 and price > sma_50:
            return {"signal": "buy", "confidence": 0.75, "reason": "Tendência de alta confirmada"}
        elif sma_50 < sma_200 and price < sma_50:
            return {"signal": "sell", "confidence": 0.75, "reason": "Tendência de baixa confirmada"}
        else:
            return {"signal": "hold", "confidence": 0.5, "reason": "Tendência não confirmada"}

    def _arbitrage_strategy(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Estratégia de Arbitragem: Aproveita diferenças de preço entre exchanges."""
        bid_price = market_data.get("bid_price", 0)
        ask_price = market_data.get("ask_price", 0)
        spread = ask_price - bid_price

        if spread > market_data.get("min_spread_threshold", 0):
            return {"signal": "arbitrage", "confidence": 0.9, "reason": f"Spread de {spread} detectado"}
        else:
            return {"signal": "hold", "confidence": 0.5, "reason": "Spread insuficiente"}

    def select_strategy(self, strategy_name: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Seleciona e executa uma estratégia."""
        if strategy_name not in self.strategies:
            logger.warning(f"Estratégia '{strategy_name}' não encontrada.")
            return {"signal": "hold", "confidence": 0.0, "reason": "Estratégia não encontrada"}

        try:
            result = self.strategies[strategy_name](market_data)
            logger.info(f"✅ Estratégia '{strategy_name}' executada: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ Erro ao executar estratégia '{strategy_name}': {e}")
            return {"signal": "hold", "confidence": 0.0, "reason": f"Erro: {str(e)}"}

    def get_available_strategies(self) -> List[str]:
        """Retorna a lista de estratégias disponíveis."""
        return list(self.strategies.keys())
