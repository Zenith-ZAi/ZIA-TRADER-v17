import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

from improved_news_analysis import AdvancedNewsAnalyzer
from config import config
from utils import setup_logging

logger = setup_logging(__name__)

class AdvancedRiskManager:
    """
    Gerenciador de risco avançado com parâmetros dinâmicos e múltiplos fatores.
    """
    
    def __init__(self):
        self.news_analyzer = AdvancedNewsAnalyzer()
        
        # Histórico de trades para análise de performance
        self.trade_history = []
        self.current_positions = {}
        self.portfolio_value = 10000.0  # Valor inicial do portfólio
        
        # Estado do sistema
        self.is_trading_halted = False
        self.halt_reason = ""
        self.last_risk_assessment = None

    def assess_trade_risk(self, signal: str, confidence: float, symbol: str,
                         market_data: pd.DataFrame, current_price: float,
                         ai_prediction_volatility: float, quantum_uncertainty: float) -> Dict:
        """
        Avalia o risco de um trade proposto com base em múltiplos fatores dinâmicos.
        
        Args:
            signal: Sinal de trading ('buy', 'sell', 'hold')
            confidence: Nível de confiança (0-100) do sinal principal
            symbol: Símbolo do ativo
            market_data: Dados históricos do mercado
            current_price: Preço atual
            ai_prediction_volatility: Volatilidade prevista pelo modelo de IA (0-1)
            quantum_uncertainty: Nível de incerteza da análise quântica (0-1)
            
        Returns:
            Avaliação de risco com recomendação
        """
        logger.info(f"🔍 Avaliando risco para {signal.upper()} em {symbol}")
        
        # 1. Verificar se o trading está suspenso
        if self.is_trading_halted:
            return {
                                'approved': False,
                'reason': f'Trading suspenso: {self.halt_reason}',
                'risk_score': 1.0,
                'position_size': 0.0
            }
        
        # 2. Análise de volatilidade (combinando dados históricos e previsão da IA)
        volatility_risk = self._assess_volatility_risk(market_data, ai_prediction_volatility)
        
        # 3. Análise de sentimento de notícias
        news_risk = self._assess_news_risk(symbol)
        
        # 4. Análise de correlação e exposição do portfólio
        portfolio_risk = self._assess_portfolio_risk(symbol, signal)
        
        # 5. Análise de performance recente
        performance_risk = self._assess_performance_risk()
        
        # 6. Análise técnica de suporte/resistência
        technical_risk = self._assess_technical_risk(market_data, current_price, signal)
        
        # 7. Risco Quântico (baseado na incerteza quântica)
        quantum_risk = quantum_uncertainty # Quanto maior a incerteza, maior o risco
        
        # Combinar todos os fatores de risco
        risk_factors = {
            'volatility_risk': volatility_risk,
            'news_risk': news_risk,
            'portfolio_risk': portfolio_risk,
            'performance_risk': performance_risk,
            'technical_risk': technical_risk,
            'quantum_risk': quantum_risk,
            'confidence_factor': confidence / 100.0
        }
        
        # Calcular score de risco agregado (0-1, onde 1 = risco máximo)
        risk_score = self._calculate_aggregate_risk(risk_factors)
        
        # Determinar tamanho da posição baseado no risco
        position_size = self._calculate_position_size(risk_score, confidence, current_price)
        
        # Decisão final
        approved = self._make_risk_decision(risk_score, confidence, risk_factors)
        
        assessment = {
            'approved': approved,
            'risk_score': risk_score,
            'position_size': position_size,
            'risk_factors': risk_factors,
            'reason': self._generate_risk_reason(approved, risk_factors, risk_score),
            'stop_loss_pct': self._calculate_stop_loss(risk_score, confidence),
            'take_profit_pct': self._calculate_take_profit(risk_score, confidence),
            'max_hold_time': self._calculate_max_hold_time(risk_score)
        }
        
        self.last_risk_assessment = assessment
        logger.info(f"✅ Avaliação concluída: {'APROVADO' if approved else 'REJEITADO'} (Risco: {risk_score:.2f})")
        
        return assessment

    def _assess_volatility_risk(self, market_data: pd.DataFrame, ai_prediction_volatility: float) -> float:
        """Avalia o risco baseado na volatilidade recente e prevista."""
        if len(market_data) < 20:
            historical_volatility = 0.5  # Risco médio se não há dados suficientes
        else:
            returns = market_data['close'].pct_change().dropna()
            historical_volatility = returns.rolling(window=20).std().iloc[-1]
        
        # Combinar volatilidade histórica e prevista
        combined_volatility = (historical_volatility + ai_prediction_volatility) / 2
        
        # Normalizar volatilidade (0-1) usando threshold da config
        normalized_volatility = min(1.0, combined_volatility / config.risk.volatility_threshold)
        
        return normalized_volatility

    def _assess_news_risk(self, symbol: str) -> float:
        """Avalia o risco baseado no sentimento das notícias."""
        try:
            sentiment_summary = self.news_analyzer.get_market_sentiment_summary([symbol.split('/')[0]])
            
            # Converter sentimento em risco (sentimento negativo = risco alto)
            sentiment_score = sentiment_summary.get('sentiment_score', 0)
            high_impact_articles = sentiment_summary.get('high_impact_articles', 0)
            
            # Risco baseado no sentimento (-1 a 1 -> 1 a 0)
            sentiment_risk = (1 - sentiment_score) / 2
            
            # Aumentar risco se há muitas notícias de alto impacto negativas
            if sentiment_score < -0.3 and high_impact_articles > 2:
                sentiment_risk = min(1.0, sentiment_risk * 1.5)
            
            return sentiment_risk
            
        except Exception as e:
            logger.warning(f"⚠️ Erro na análise de notícias: {e}")
            return 0.3  # Risco médio-baixo se não conseguir analisar

    def _assess_portfolio_risk(self, symbol: str, signal: str) -> float:
        """Avalia o risco baseado na exposição atual do portfólio e correlação."""
        # Verificar exposição atual ao símbolo
        current_exposure = self.current_positions.get(symbol, 0)
        
        # Calcular exposição total do portfólio
        total_exposure = sum(abs(pos) for pos in self.current_positions.values())
        exposure_ratio = total_exposure / self.portfolio_value
        
        # Risco aumenta com a exposição
        portfolio_risk = min(1.0, exposure_ratio / config.risk.max_exposure_ratio)
        
        # Penalizar se já há posição grande no mesmo símbolo
        if abs(current_exposure) > config.trading.max_position_size * self.portfolio_value:
            portfolio_risk = min(1.0, portfolio_risk * 1.5)
        
        # TODO: Adicionar análise de correlação entre ativos no portfólio
        # Isso exigiria dados históricos de múltiplos ativos para calcular a matriz de covariância
        
        return portfolio_risk

    def _assess_performance_risk(self) -> float:
        """Avalia o risco baseado na performance recente."""
        if len(self.trade_history) < 5:
            return 0.2  # Risco baixo se não há histórico suficiente
        
        # Analisar últimos trades
        recent_trades = self.trade_history[-config.trading.consecutive_losses_limit * 2:] # Olhar um pouco mais para trás
        
        # Contar perdas consecutivas
        consecutive_losses = 0
        for trade in reversed(recent_trades):
            if trade.get('pnl', 0) < 0:
                consecutive_losses += 1
            else:
                break
        
        # Calcular drawdown atual
        portfolio_values = [trade.get('portfolio_value', self.portfolio_value) for trade in recent_trades]
        if portfolio_values:
            peak_value = max(portfolio_values)
            current_drawdown = (peak_value - self.portfolio_value) / peak_value
        else:
            current_drawdown = 0
        
        # Calcular risco baseado na performance
        performance_risk = 0.0
        
        # Penalizar perdas consecutivas
        if consecutive_losses >= config.trading.consecutive_losses_limit:
            performance_risk += 0.5
        
        # Penalizar drawdown alto
        if current_drawdown > config.trading.max_drawdown:
            performance_risk += 0.4
        
        return min(1.0, performance_risk)

    def _assess_technical_risk(self, market_data: pd.DataFrame, current_price: float, signal: str) -> float:
        """Avalia o risco baseado em indicadores técnicos mais robustos."""
        if len(market_data) < 50:
            return 0.3  # Risco médio se não há dados suficientes
        
        technical_risk = 0.0
        
        # RSI
        delta = market_data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        if signal == 'buy' and current_rsi > 70:
            technical_risk += 0.3  # Sobrecomprado
        elif signal == 'sell' and current_rsi < 30:
            technical_risk += 0.3  # Sobrevendido
        
        # Bandas de Bollinger
        sma_20 = market_data['close'].rolling(window=20).mean().iloc[-1]
        std_20 = market_data['close'].rolling(window=20).std().iloc[-1]
        upper_band = sma_20 + (std_20 * 2)
        lower_band = sma_20 - (std_20 * 2)
        
        if signal == 'buy' and current_price < lower_band:
            technical_risk -= 0.1 # Sinal de compra forte se abaixo da banda inferior
        elif signal == 'sell' and current_price > upper_band:
            technical_risk -= 0.1 # Sinal de venda forte se acima da banda superior
        
        # Média Móvel Exponencial (EMA) para tendência
        ema_50 = market_data['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        ema_200 = market_data['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        
        if signal == 'buy' and ema_50 < ema_200:
            technical_risk += 0.2 # Comprando contra tendência de baixa de longo prazo
        elif signal == 'sell' and ema_50 > ema_200:
            technical_risk += 0.2 # Vendendo contra tendência de alta de longo prazo

        return min(1.0, technical_risk)

    def _calculate_aggregate_risk(self, risk_factors: Dict) -> float:
        """
        Calcula o score de risco agregado usando pesos dinâmicos e non-linearidade.
        """
        # Pesos para cada fator de risco (ajustados)
        weights = {
            'volatility_risk': 0.20,
            'news_risk': 0.25,
            'portfolio_risk': 0.15,
            'performance_risk': 0.15,
            'technical_risk': 0.10,
            'quantum_risk': 0.15 # Novo fator de risco
        }
        
        # Calcular média ponderada
        weighted_risk = sum(
            risk_factors.get(factor, 0) * weight 
            for factor, weight in weights.items()
        )
        
        # Ajustar baseado na confiança (alta confiança reduz risco, mas com limite)
        confidence_adjustment = 1 - (risk_factors.get('confidence_factor', 0.5) * 0.3) # Maior impacto da confiança
        
        # Adicionar um fator de penalidade não-linear para risco muito alto
        if weighted_risk > 0.7:
            weighted_risk *= 1.2 # Penalidade de 20% para risco alto
        
        return min(1.0, weighted_risk * confidence_adjustment)

    def _calculate_position_size(self, risk_score: float, confidence: float, current_price: float) -> float:
        """
        Calcula o tamanho da posição baseado no risco e confiança, usando o capital do portfólio.
        """
        # Tamanho base baseado na confiança e risco máximo do portfólio
        # Usar a regra de Kelly Criterion ou uma fração fixa do capital de risco
        
        # Exemplo simplificado: fração do capital de risco disponível
        capital_at_risk = self.portfolio_value * config.trading.max_portfolio_risk
        
        # Ajustar capital de risco pela confiança e score de risco
        adjusted_capital_at_risk = capital_at_risk * (confidence / 100.0) * (1 - risk_score)
        
        # Tamanho da posição em USD
        position_size_usd = adjusted_capital_at_risk / config.trading.max_portfolio_risk # Para que o risco por trade seja o max_portfolio_risk
        
        # Limitar ao tamanho máximo da posição como % do portfólio
        position_size_usd = min(position_size_usd, self.portfolio_value * config.trading.max_position_size)
        
        # Converter para quantidade do ativo
        position_quantity = position_size_usd / current_price
        
        return max(0.0, position_quantity)

    def _make_risk_decision(self, risk_score: float, confidence: float, risk_factors: Dict) -> bool:
        """
        Toma a decisão final sobre aprovação do trade com critérios mais rigorosos.
        """
        # Critérios de rejeição absoluta
        if risk_score > 0.7: # Limiar de risco mais baixo para rejeição
            logger.warning(f"Trade rejeitado: Risco agregado ({risk_score:.2f}) muito alto.")
            return False
        
        if confidence < config.trading.min_confidence:  # Usar confiança mínima da config
            logger.warning(f"Trade rejeitado: Confiança ({confidence:.2f}%) abaixo do mínimo necessário ({config.trading.min_confidence}%).")
            return False
        
        if risk_factors.get('news_risk', 0) > config.risk.news_impact_threshold:  # Notícias muito negativas
            logger.warning(f"Trade rejeitado: Sentimento de notícias muito negativo ({risk_factors['news_risk']:.2f}).")
            return False
        
        if risk_factors.get('performance_risk', 0) > 0.5:  # Performance ruim recente (ajustado)
            logger.warning(f"Trade rejeitado: Performance recente ruim ({risk_factors['performance_risk']:.2f}).")
            return False
        
        if risk_factors.get('quantum_risk', 0) > 0.8: # Alta incerteza quântica
            logger.warning(f"Trade rejeitado: Alta incerteza quântica ({risk_factors['quantum_risk']:.2f}).")
            return False

        logger.info("Trade aprovado pelos critérios de risco.")
        return True

    def _generate_risk_reason(self, approved: bool, risk_factors: Dict, risk_score: float) -> str:
        """
        Gera explicação detalhada da decisão de risco.
        """
        if approved:
            return f"Trade aprovado com risco controlado ({risk_score:.2f}). Fatores: {json.dumps({k: round(v, 2) for k, v in risk_factors.items()})}"
        
        reasons = []
        if risk_score > 0.7:
            reasons.append(f"risco agregado muito alto ({risk_score:.2f})")
        if risk_factors.get('confidence_factor', 0) * 100 < config.trading.min_confidence:
            reasons.append(f"confiança insuficiente ({risk_factors['confidence_factor']*100:.2f}%)")
        if risk_factors.get('news_risk', 0) > config.risk.news_impact_threshold:
            reasons.append(f"sentimento de notícias muito negativo ({risk_factors['news_risk']:.2f})")
        if risk_factors.get('performance_risk', 0) > 0.5:
            reasons.append(f"performance recente ruim ({risk_factors['performance_risk']:.2f})")
        if risk_factors.get('volatility_risk', 0) > 0.7: # Ajustado
            reasons.append(f"volatilidade excessiva ({risk_factors['volatility_risk']:.2f})")
        if risk_factors.get('quantum_risk', 0) > 0.8:
            reasons.append(f"alta incerteza quântica ({risk_factors['quantum_risk']:.2f})")
        
        return f"Trade rejeitado: {', '.join(reasons)}. Fatores: {json.dumps({k: round(v, 2) for k, v in risk_factors.items()})}"

    def _calculate_stop_loss(self, risk_score: float, confidence: float) -> float:
        """
        Calcula a porcentagem de stop-loss dinamicamente.
        """
        base_stop = config.trading.base_stop_loss
        risk_adjustment = 1 + risk_score * 0.5  # Mais risco = stop mais largo, mas com menor impacto
        confidence_adjustment = 1 + (1 - (confidence / 100.0)) * 0.5 # Menos confiança = stop mais largo
        
        return min(0.10, base_stop * risk_adjustment * confidence_adjustment) # Limite máximo de 10%

    def _calculate_take_profit(self, risk_score: float, confidence: float) -> float:
        """
        Calcula a porcentagem de take-profit dinamicamente.
        """
        base_tp = config.trading.base_take_profit
        confidence_adjustment = 1 + (confidence / 100.0) * 0.5 # Mais confiança = TP mais distante
        risk_adjustment = 1 + (1 - risk_score) * 0.5 # Menos risco = TP mais distante
        
        return min(0.20, base_tp * confidence_adjustment * risk_adjustment) # Limite máximo de 20%

    def _calculate_max_hold_time(self, risk_score: float) -> int:
        """
        Calcula o tempo máximo de manutenção da posição (em minutos) dinamicamente.
        """
        base_time = 120  # 2 horas base
        risk_adjustment = 1 - risk_score * 0.75  # Mais risco = menos tempo, maior impacto
        
        return max(30, int(base_time * risk_adjustment)) # Mínimo de 30 minutos

    def update_portfolio(self, symbol: str, quantity: float, price: float, pnl: float):
        """
        Atualiza o estado do portfólio após um trade.
        """
        # Atualizar posição (aqui, a posição é o tamanho total, não o delta)
        # A lógica de `current_positions` deve ser gerenciada pelo OrderExecutor
        # Este método é para registrar o PnL e o valor do portfólio
        
        # Atualizar valor do portfólio
        self.portfolio_value += pnl
        
        # Adicionar ao histórico
        trade_record = {
            'timestamp': datetime.now(),
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'pnl': pnl,
            'portfolio_value': self.portfolio_value
        }
        self.trade_history.append(trade_record)
        
        # Verificar se precisa suspender trading
        self._check_trading_halt()
        logger.info(f"Portfólio atualizado: Valor = ${self.portfolio_value:.2f}, PnL do último trade = ${pnl:.2f}")

    def _check_trading_halt(self):
        """
        Verifica se o trading deve ser suspenso com critérios mais sofisticados.
        """
        if len(self.trade_history) < 10: # Precisa de mais histórico para avaliar
            return
        
        # Verificar drawdown
        recent_values = [trade['portfolio_value'] for trade in self.trade_history[-20:]] # Olhar mais trades
        if not recent_values:
            return
        
        peak_value = max(recent_values)
        current_drawdown = (peak_value - self.portfolio_value) / peak_value
        
        if current_drawdown > config.trading.max_drawdown:
            self.is_trading_halted = True
            self.halt_reason = f"Drawdown excessivo: {current_drawdown:.1%}"
            logger.critical(f"🚨 Trading suspenso: {self.halt_reason}")
            return
        
        # Verificar perdas consecutivas
        consecutive_losses = 0
        for trade in reversed(self.trade_history[-config.trading.consecutive_losses_limit * 2:]):
            if trade['pnl'] < 0:
                consecutive_losses += 1
            else:
                break
        
        if consecutive_losses >= config.trading.consecutive_losses_limit:
            self.is_trading_halted = True
            self.halt_reason = f"Muitas perdas consecutivas: {consecutive_losses}"
            logger.critical(f"🚨 Trading suspenso: {self.halt_reason}")

    def resume_trading(self):
        """
        Resume o trading após suspensão.
        """
        self.is_trading_halted = False
        self.halt_reason = ""
        logger.info("✅ Trading resumido")

    def get_risk_status(self) -> Dict:
        """
        Retorna o status atual do gerenciamento de risco.
        """
        return {
            'is_trading_halted': self.is_trading_halted,
            'halt_reason': self.halt_reason,
            'portfolio_value': self.portfolio_value,
            'total_trades': len(self.trade_history),
            'last_assessment': self.last_risk_assessment
        }

if __name__ == "__main__":
    # Teste do gerenciador de risco avançado
    risk_manager = AdvancedRiskManager()
    
    # Simular dados de mercado
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1H')
    prices = 50000 + np.cumsum(np.random.normal(0, 100, 100))
    market_data = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices * 1.01,
        'low': prices * 0.99,
        'close': prices,
        'volume': np.random.randint(100, 1000, 100)
    })
    
    logger.info("🛡️ Testando gerenciador de risco avançado...")
    
    # Avaliar um trade de compra
    assessment = risk_manager.assess_trade_risk(
        signal='buy',
        confidence=98.5,
        symbol='BTC/USDT',
        market_data=market_data,
        current_price=prices[-1],
        ai_prediction_volatility=0.1, # Exemplo de previsão de volatilidade da IA
        quantum_uncertainty=0.2      # Exemplo de incerteza quântica
    )
    
    logger.info(f"\n📊 Avaliação de Risco:")
    logger.info(f"   Aprovado: {'✅ SIM' if assessment['approved'] else '❌ NÃO'}")
    logger.info(f"   Score de Risco: {assessment['risk_score']:.2f}")
    logger.info(f"   Tamanho da Posição: {assessment['position_size']:.4f}")
    logger.info(f"   Razão: {assessment['reason']}")
    logger.info(f"   Stop-Loss: {assessment['stop_loss_pct']:.1%}")
    logger.info(f"   Take-Profit: {assessment['take_profit_pct']:.1%}")
    
    # Simular alguns trades
    logger.info(f"\n🔄 Simulando trades...")
    for i in range(5):
        pnl = np.random.normal(-50, 100)  # PnL aleatório, alguns negativos para testar halt
        risk_manager.update_portfolio('BTC/USDT', 0.001, prices[-1], pnl)
        logger.info(f"   Trade {i+1}: PnL = ${pnl:.2f}, Portfolio = ${risk_manager.portfolio_value:.2f}")
    
    # Status final
    status = risk_manager.get_risk_status()
    logger.info(f"\n📈 Status do Risco:")
    logger.info(f"   Trading Ativo: {'✅ SIM' if not status['is_trading_halted'] else '❌ NÃO'}")
    logger.info(f"   Valor do Portfolio: ${status['portfolio_value']:.2f}")
    logger.info(f"   Total de Trades: {status['total_trades']}")
    logger.info("   Razão de Suspensão: " + status["halt_reason"])



