"""
Sistema de Aprimoramento de Robustez - RoboTrader
Ferramentas para lidar com cenários extremos de mercado e aumentar a robustez do algoritmo.
"""

import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple, Callable
from dataclasses import dataclass, field
import logging
from enum import Enum
import warnings
from scipy import stats
from sklearn.preprocessing import RobustScaler
from sklearn.ensemble import IsolationForest
import joblib

# Importações locais
from config import config
from utils import setup_logging
from debugging_system import debug_function, track_decision, debug_context

logger = setup_logging(__name__)

class MarketRegime(Enum):
    """Regimes de mercado"""
    NORMAL = "normal"
    HIGH_VOLATILITY = "high_volatility"
    TRENDING = "trending"
    SIDEWAYS = "sideways"
    CRASH = "crash"
    BUBBLE = "bubble"
    RECOVERY = "recovery"
    EXTREME_VOLATILITY = "extreme_volatility"

class RiskLevel(Enum):
    """Níveis de risco"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    EXTREME = "extreme"

@dataclass
class MarketCondition:
    """Condição de mercado"""
    timestamp: datetime
    regime: MarketRegime
    volatility: float
    trend_strength: float
    liquidity_score: float
    risk_level: RiskLevel
    confidence: float
    indicators: Dict[str, float] = field(default_factory=dict)

@dataclass
class RobustnessConfig:
    """Configuração de robustez"""
    # Detecção de regimes
    volatility_window: int = 20
    trend_window: int = 50
    regime_confidence_threshold: float = 0.7
    
    # Limites de segurança
    max_position_size_normal: float = 0.1  # 10%
    max_position_size_volatile: float = 0.05  # 5%
    max_position_size_extreme: float = 0.02  # 2%
    
    # Stop losses adaptativos
    stop_loss_normal: float = 0.05  # 5%
    stop_loss_volatile: float = 0.03  # 3%
    stop_loss_extreme: float = 0.02  # 2%
    
    # Filtros de qualidade
    min_liquidity_score: float = 0.3
    max_spread_threshold: float = 0.01  # 1%
    min_volume_ratio: float = 0.5
    
    # Recuperação de falhas
    circuit_breaker_threshold: float = 0.1  # 10% loss
    cooldown_period_minutes: int = 30
    max_daily_trades: int = 50
    
    # Adaptação dinâmica
    enable_dynamic_adaptation: bool = True
    adaptation_learning_rate: float = 0.1
    performance_window: int = 100

class MarketRegimeDetector:
    """Detector de regimes de mercado"""
    
    def __init__(self, config: RobustnessConfig):
        self.config = config
        self.regime_history = []
        self.volatility_model = None
        self.trend_model = None
        
        # Inicializar modelos
        self._initialize_models()
    
    def _initialize_models(self):
        """Inicializa modelos de detecção"""
        # Modelo de detecção de anomalias para volatilidade extrema
        self.volatility_model = IsolationForest(
            contamination=0.1,
            random_state=42
        )
        
        # Scaler robusto para normalização
        self.scaler = RobustScaler()
    
    @debug_function
    async def detect_regime(self, data: pd.DataFrame) -> MarketCondition:
        """Detecta regime atual do mercado"""
        try:
            if len(data) < self.config.volatility_window:
                return self._default_market_condition()
            
            # Calcular indicadores
            indicators = self._calculate_indicators(data)
            
            # Detectar regime
            regime = await self._classify_regime(indicators)
            
            # Calcular nível de risco
            risk_level = self._assess_risk_level(indicators, regime)
            
            # Calcular confiança
            confidence = self._calculate_confidence(indicators, regime)
            
            condition = MarketCondition(
                timestamp=datetime.now(),
                regime=regime,
                volatility=indicators['volatility'],
                trend_strength=indicators['trend_strength'],
                liquidity_score=indicators['liquidity_score'],
                risk_level=risk_level,
                confidence=confidence,
                indicators=indicators
            )
            
            self.regime_history.append(condition)
            
            # Manter apenas últimas 1000 observações
            if len(self.regime_history) > 1000:
                self.regime_history = self.regime_history[-1000:]
            
            return condition
            
        except Exception as e:
            logger.error(f"Erro na detecção de regime: {e}")
            return self._default_market_condition()
    
    def _calculate_indicators(self, data: pd.DataFrame) -> Dict[str, float]:
        """Calcula indicadores de mercado"""
        indicators = {}
        
        try:
            # Volatilidade realizada
            returns = data['close'].pct_change().dropna()
            volatility = returns.rolling(self.config.volatility_window).std().iloc[-1]
            indicators['volatility'] = volatility * np.sqrt(252)  # Anualizada
            
            # Força da tendência
            sma_short = data['close'].rolling(10).mean()
            sma_long = data['close'].rolling(50).mean()
            trend_strength = abs((sma_short.iloc[-1] - sma_long.iloc[-1]) / sma_long.iloc[-1])
            indicators['trend_strength'] = trend_strength
            
            # Score de liquidez (baseado em volume)
            volume_ma = data['volume'].rolling(20).mean()
            current_volume = data['volume'].iloc[-1]
            liquidity_score = min(current_volume / volume_ma.iloc[-1], 2.0) / 2.0
            indicators['liquidity_score'] = liquidity_score
            
            # Spread estimado (high-low como proxy)
            spread = (data['high'] - data['low']) / data['close']
            avg_spread = spread.rolling(20).mean().iloc[-1]
            indicators['avg_spread'] = avg_spread
            
            # Momentum
            momentum = (data['close'].iloc[-1] - data['close'].iloc[-20]) / data['close'].iloc[-20]
            indicators['momentum'] = momentum
            
            # Volatilidade de volatilidade
            vol_of_vol = returns.rolling(20).std().rolling(10).std().iloc[-1]
            indicators['vol_of_vol'] = vol_of_vol
            
            # Skewness e Kurtosis
            if len(returns) >= 20:
                recent_returns = returns.tail(20)
                indicators['skewness'] = stats.skew(recent_returns)
                indicators['kurtosis'] = stats.kurtosis(recent_returns)
            else:
                indicators['skewness'] = 0.0
                indicators['kurtosis'] = 0.0
            
            # Drawdown atual
            peak = data['close'].rolling(50, min_periods=1).max()
            drawdown = (data['close'] - peak) / peak
            indicators['current_drawdown'] = drawdown.iloc[-1]
            
            # VIX proxy (volatilidade implícita estimada)
            vix_proxy = volatility * (1 + abs(indicators['skewness']) + indicators['kurtosis'] / 10)
            indicators['vix_proxy'] = vix_proxy
            
        except Exception as e:
            logger.error(f"Erro no cálculo de indicadores: {e}")
            # Valores padrão em caso de erro
            indicators = {
                'volatility': 0.2,
                'trend_strength': 0.0,
                'liquidity_score': 0.5,
                'avg_spread': 0.01,
                'momentum': 0.0,
                'vol_of_vol': 0.0,
                'skewness': 0.0,
                'kurtosis': 0.0,
                'current_drawdown': 0.0,
                'vix_proxy': 0.2
            }
        
        return indicators
    
    @track_decision("regime_classification", confidence=0.8, reasoning="Market regime classification")
    async def _classify_regime(self, indicators: Dict[str, float]) -> MarketRegime:
        """Classifica regime de mercado"""
        volatility = indicators['volatility']
        trend_strength = indicators['trend_strength']
        momentum = indicators['momentum']
        drawdown = indicators['current_drawdown']
        vix_proxy = indicators['vix_proxy']
        kurtosis = indicators['kurtosis']
        
        # Regimes extremos primeiro
        if volatility > 0.8 or vix_proxy > 0.8 or kurtosis > 5:
            return MarketRegime.EXTREME_VOLATILITY
        
        if drawdown < -0.2 and momentum < -0.1:
            return MarketRegime.CRASH
        
        if momentum > 0.3 and volatility > 0.5 and trend_strength > 0.1:
            return MarketRegime.BUBBLE
        
        if drawdown < -0.1 and momentum > 0.05:
            return MarketRegime.RECOVERY
        
        # Regimes normais
        if volatility > 0.4:
            return MarketRegime.HIGH_VOLATILITY
        
        if trend_strength > 0.05:
            return MarketRegime.TRENDING
        
        if trend_strength < 0.02 and volatility < 0.3:
            return MarketRegime.SIDEWAYS
        
        return MarketRegime.NORMAL
    
    def _assess_risk_level(self, indicators: Dict[str, float], regime: MarketRegime) -> RiskLevel:
        """Avalia nível de risco"""
        volatility = indicators['volatility']
        liquidity = indicators['liquidity_score']
        spread = indicators['avg_spread']
        
        # Regime extremo = risco extremo
        if regime in [MarketRegime.EXTREME_VOLATILITY, MarketRegime.CRASH]:
            return RiskLevel.EXTREME
        
        if regime == MarketRegime.BUBBLE:
            return RiskLevel.VERY_HIGH
        
        # Baseado em volatilidade e liquidez
        risk_score = 0.0
        
        # Componente de volatilidade
        if volatility > 0.6:
            risk_score += 3
        elif volatility > 0.4:
            risk_score += 2
        elif volatility > 0.2:
            risk_score += 1
        
        # Componente de liquidez
        if liquidity < 0.3:
            risk_score += 2
        elif liquidity < 0.5:
            risk_score += 1
        
        # Componente de spread
        if spread > 0.02:
            risk_score += 2
        elif spread > 0.01:
            risk_score += 1
        
        # Mapear para enum
        if risk_score >= 5:
            return RiskLevel.VERY_HIGH
        elif risk_score >= 4:
            return RiskLevel.HIGH
        elif risk_score >= 2:
            return RiskLevel.MEDIUM
        elif risk_score >= 1:
            return RiskLevel.LOW
        else:
            return RiskLevel.VERY_LOW
    
    def _calculate_confidence(self, indicators: Dict[str, float], regime: MarketRegime) -> float:
        """Calcula confiança na classificação"""
        # Confiança baseada na consistência dos indicadores
        volatility = indicators['volatility']
        trend_strength = indicators['trend_strength']
        
        confidence = 0.5  # Base
        
        # Regimes extremos têm alta confiança se indicadores são claros
        if regime == MarketRegime.EXTREME_VOLATILITY and volatility > 0.8:
            confidence = 0.95
        elif regime == MarketRegime.CRASH and indicators['current_drawdown'] < -0.2:
            confidence = 0.9
        elif regime == MarketRegime.TRENDING and trend_strength > 0.1:
            confidence = 0.8
        elif regime == MarketRegime.SIDEWAYS and trend_strength < 0.02:
            confidence = 0.75
        else:
            confidence = 0.6
        
        return confidence
    
    def _default_market_condition(self) -> MarketCondition:
        """Condição de mercado padrão"""
        return MarketCondition(
            timestamp=datetime.now(),
            regime=MarketRegime.NORMAL,
            volatility=0.2,
            trend_strength=0.0,
            liquidity_score=0.5,
            risk_level=RiskLevel.MEDIUM,
            confidence=0.5
        )

class AdaptiveRiskManager:
    """Gerenciador de risco adaptativo"""
    
    def __init__(self, config: RobustnessConfig):
        self.config = config
        self.position_limits = {}
        self.stop_losses = {}
        self.circuit_breaker_active = False
        self.circuit_breaker_until = None
        self.daily_trade_count = 0
        self.last_trade_date = None
        
        # Histórico de performance
        self.performance_history = []
        
        # Parâmetros adaptativos
        self.adaptive_params = {
            'position_size_multiplier': 1.0,
            'stop_loss_multiplier': 1.0,
            'confidence_threshold': 0.5
        }
    
    @debug_function
    async def assess_trade_viability(self, symbol: str, signal: Dict[str, Any], 
                                   market_condition: MarketCondition) -> Dict[str, Any]:
        """Avalia viabilidade de um trade"""
        try:
            with debug_context(symbol=symbol, regime=market_condition.regime.value):
                # Verificar circuit breaker
                if self._is_circuit_breaker_active():
                    return {
                        'approved': False,
                        'reason': 'circuit_breaker_active',
                        'recommended_action': 'wait'
                    }
                
                # Verificar limite diário de trades
                if self._is_daily_limit_exceeded():
                    return {
                        'approved': False,
                        'reason': 'daily_limit_exceeded',
                        'recommended_action': 'wait_next_day'
                    }
                
                # Verificar qualidade do sinal
                signal_quality = self._assess_signal_quality(signal, market_condition)
                if signal_quality['score'] < 0.3:
                    return {
                        'approved': False,
                        'reason': 'poor_signal_quality',
                        'signal_quality': signal_quality,
                        'recommended_action': 'improve_signal'
                    }
                
                # Calcular tamanho de posição adaptativo
                position_size = self._calculate_adaptive_position_size(symbol, market_condition)
                
                # Calcular stop loss adaptativo
                stop_loss = self._calculate_adaptive_stop_loss(market_condition)
                
                # Verificar liquidez
                if market_condition.liquidity_score < self.config.min_liquidity_score:
                    return {
                        'approved': False,
                        'reason': 'insufficient_liquidity',
                        'liquidity_score': market_condition.liquidity_score,
                        'recommended_action': 'wait_for_liquidity'
                    }
                
                return {
                    'approved': True,
                    'position_size': position_size,
                    'stop_loss': stop_loss,
                    'risk_level': market_condition.risk_level.value,
                    'signal_quality': signal_quality,
                    'market_regime': market_condition.regime.value
                }
                
        except Exception as e:
            logger.error(f"Erro na avaliação de viabilidade: {e}")
            return {
                'approved': False,
                'reason': 'assessment_error',
                'error': str(e),
                'recommended_action': 'retry_later'
            }
    
    def _is_circuit_breaker_active(self) -> bool:
        """Verifica se circuit breaker está ativo"""
        if not self.circuit_breaker_active:
            return False
        
        if self.circuit_breaker_until and datetime.now() > self.circuit_breaker_until:
            self.circuit_breaker_active = False
            self.circuit_breaker_until = None
            logger.info("Circuit breaker desativado")
            return False
        
        return True
    
    def _is_daily_limit_exceeded(self) -> bool:
        """Verifica se limite diário foi excedido"""
        today = datetime.now().date()
        
        if self.last_trade_date != today:
            self.daily_trade_count = 0
            self.last_trade_date = today
        
        return self.daily_trade_count >= self.config.max_daily_trades
    
    def _assess_signal_quality(self, signal: Dict[str, Any], 
                              market_condition: MarketCondition) -> Dict[str, Any]:
        """Avalia qualidade do sinal"""
        quality_score = 0.0
        factors = {}
        
        # Confiança do sinal
        confidence = signal.get('confidence', 0.0)
        factors['confidence'] = confidence
        quality_score += confidence * 0.4
        
        # Consistência entre componentes
        scores = signal.get('scores', {})
        if scores:
            score_values = list(scores.values())
            consistency = 1.0 - np.std(score_values) if len(score_values) > 1 else 1.0
            factors['consistency'] = consistency
            quality_score += consistency * 0.3
        
        # Adequação ao regime de mercado
        regime_adequacy = self._assess_regime_adequacy(signal, market_condition)
        factors['regime_adequacy'] = regime_adequacy
        quality_score += regime_adequacy * 0.3
        
        return {
            'score': quality_score,
            'factors': factors,
            'grade': self._score_to_grade(quality_score)
        }
    
    def _assess_regime_adequacy(self, signal: Dict[str, Any], 
                               market_condition: MarketCondition) -> float:
        """Avalia adequação do sinal ao regime de mercado"""
        regime = market_condition.regime
        action = signal.get('action', 'hold')
        
        # Regimes extremos: preferir hold
        if regime in [MarketRegime.EXTREME_VOLATILITY, MarketRegime.CRASH]:
            return 0.8 if action == 'hold' else 0.2
        
        # Bubble: preferir sell
        if regime == MarketRegime.BUBBLE:
            return 0.8 if action == 'sell' else 0.4
        
        # Recovery: preferir buy
        if regime == MarketRegime.RECOVERY:
            return 0.8 if action == 'buy' else 0.4
        
        # Trending: qualquer direção ok
        if regime == MarketRegime.TRENDING:
            return 0.7 if action != 'hold' else 0.5
        
        # Sideways: preferir hold
        if regime == MarketRegime.SIDEWAYS:
            return 0.6 if action == 'hold' else 0.4
        
        # Normal: qualquer ação ok
        return 0.6
    
    def _calculate_adaptive_position_size(self, symbol: str, 
                                        market_condition: MarketCondition) -> float:
        """Calcula tamanho de posição adaptativo"""
        base_size = self.config.max_position_size_normal
        
        # Ajustar baseado no regime
        if market_condition.regime == MarketRegime.EXTREME_VOLATILITY:
            base_size = self.config.max_position_size_extreme
        elif market_condition.regime in [MarketRegime.HIGH_VOLATILITY, MarketRegime.CRASH, MarketRegime.BUBBLE]:
            base_size = self.config.max_position_size_volatile
        
        # Ajustar baseado no nível de risco
        risk_multiplier = {
            RiskLevel.VERY_LOW: 1.2,
            RiskLevel.LOW: 1.0,
            RiskLevel.MEDIUM: 0.8,
            RiskLevel.HIGH: 0.6,
            RiskLevel.VERY_HIGH: 0.4,
            RiskLevel.EXTREME: 0.2
        }.get(market_condition.risk_level, 0.8)
        
        # Ajustar baseado na confiança
        confidence_multiplier = market_condition.confidence
        
        # Aplicar multiplicador adaptativo
        adaptive_multiplier = self.adaptive_params['position_size_multiplier']
        
        final_size = base_size * risk_multiplier * confidence_multiplier * adaptive_multiplier
        
        return min(final_size, self.config.max_position_size_normal)
    
    def _calculate_adaptive_stop_loss(self, market_condition: MarketCondition) -> float:
        """Calcula stop loss adaptativo"""
        base_stop = self.config.stop_loss_normal
        
        # Ajustar baseado no regime
        if market_condition.regime == MarketRegime.EXTREME_VOLATILITY:
            base_stop = self.config.stop_loss_extreme
        elif market_condition.regime in [MarketRegime.HIGH_VOLATILITY, MarketRegime.CRASH]:
            base_stop = self.config.stop_loss_volatile
        
        # Ajustar baseado na volatilidade
        volatility_multiplier = 1.0 + (market_condition.volatility - 0.2) * 0.5
        volatility_multiplier = max(0.5, min(2.0, volatility_multiplier))
        
        # Aplicar multiplicador adaptativo
        adaptive_multiplier = self.adaptive_params['stop_loss_multiplier']
        
        final_stop = base_stop * volatility_multiplier * adaptive_multiplier
        
        return min(final_stop, 0.15)  # Máximo de 15%
    
    def _score_to_grade(self, score: float) -> str:
        """Converte score para grade"""
        if score >= 0.8:
            return 'A'
        elif score >= 0.6:
            return 'B'
        elif score >= 0.4:
            return 'C'
        elif score >= 0.2:
            return 'D'
        else:
            return 'F'
    
    async def activate_circuit_breaker(self, reason: str):
        """Ativa circuit breaker"""
        self.circuit_breaker_active = True
        self.circuit_breaker_until = datetime.now() + timedelta(minutes=self.config.cooldown_period_minutes)
        
        logger.warning(f"Circuit breaker ativado: {reason}")
        logger.info(f"Reativação em: {self.circuit_breaker_until}")
    
    def record_trade_result(self, symbol: str, pnl: float, market_condition: MarketCondition):
        """Registra resultado de trade para adaptação"""
        self.daily_trade_count += 1
        
        trade_result = {
            'timestamp': datetime.now(),
            'symbol': symbol,
            'pnl': pnl,
            'regime': market_condition.regime,
            'risk_level': market_condition.risk_level,
            'volatility': market_condition.volatility
        }
        
        self.performance_history.append(trade_result)
        
        # Manter apenas últimos N resultados
        if len(self.performance_history) > self.config.performance_window:
            self.performance_history = self.performance_history[-self.config.performance_window:]
        
        # Verificar se precisa ativar circuit breaker
        if pnl < -self.config.circuit_breaker_threshold:
            asyncio.create_task(self.activate_circuit_breaker(f"Large loss: {pnl:.2%}"))
        
        # Adaptação dinâmica
        if self.config.enable_dynamic_adaptation:
            self._adapt_parameters()
    
    def _adapt_parameters(self):
        """Adapta parâmetros baseado na performance"""
        if len(self.performance_history) < 20:
            return
        
        recent_trades = self.performance_history[-20:]
        recent_pnl = [t['pnl'] for t in recent_trades]
        
        # Calcular performance
        win_rate = len([p for p in recent_pnl if p > 0]) / len(recent_pnl)
        avg_pnl = np.mean(recent_pnl)
        
        learning_rate = self.config.adaptation_learning_rate
        
        # Adaptar tamanho de posição
        if win_rate > 0.6 and avg_pnl > 0:
            # Performance boa: aumentar ligeiramente
            self.adaptive_params['position_size_multiplier'] *= (1 + learning_rate * 0.1)
        elif win_rate < 0.4 or avg_pnl < 0:
            # Performance ruim: diminuir
            self.adaptive_params['position_size_multiplier'] *= (1 - learning_rate * 0.2)
        
        # Adaptar stop loss
        if avg_pnl < -0.02:  # Perdas grandes
            # Apertar stop loss
            self.adaptive_params['stop_loss_multiplier'] *= (1 - learning_rate * 0.1)
        elif win_rate > 0.7:
            # Relaxar stop loss ligeiramente
            self.adaptive_params['stop_loss_multiplier'] *= (1 + learning_rate * 0.05)
        
        # Limitar adaptações
        self.adaptive_params['position_size_multiplier'] = np.clip(
            self.adaptive_params['position_size_multiplier'], 0.2, 2.0
        )
        self.adaptive_params['stop_loss_multiplier'] = np.clip(
            self.adaptive_params['stop_loss_multiplier'], 0.5, 2.0
        )
        
        logger.info(f"Parâmetros adaptados: {self.adaptive_params}")

class ErrorRecoverySystem:
    """Sistema de recuperação de erros robusto"""
    
    def __init__(self):
        self.recovery_strategies = {}
        self.error_patterns = {}
        self.recovery_success_rate = {}
    
    def register_recovery_strategy(self, error_pattern: str, strategy: Callable):
        """Registra estratégia de recuperação"""
        self.recovery_strategies[error_pattern] = strategy
        self.recovery_success_rate[error_pattern] = []
    
    @debug_function
    async def handle_error(self, error: Exception, context: Dict[str, Any]) -> bool:
        """Trata erro com estratégias de recuperação"""
        error_type = type(error).__name__
        error_message = str(error)
        
        # Identificar padrão de erro
        pattern = self._identify_error_pattern(error_type, error_message, context)
        
        if pattern not in self.recovery_strategies:
            logger.warning(f"Nenhuma estratégia de recuperação para padrão: {pattern}")
            return False
        
        try:
            strategy = self.recovery_strategies[pattern]
            success = await strategy(error, context)
            
            # Registrar resultado
            self.recovery_success_rate[pattern].append(success)
            
            if success:
                logger.info(f"Recuperação bem-sucedida para padrão: {pattern}")
            else:
                logger.warning(f"Recuperação falhou para padrão: {pattern}")
            
            return success
            
        except Exception as recovery_error:
            logger.error(f"Erro na estratégia de recuperação: {recovery_error}")
            return False
    
    def _identify_error_pattern(self, error_type: str, error_message: str, 
                               context: Dict[str, Any]) -> str:
        """Identifica padrão de erro"""
        # Padrões específicos
        if "connection" in error_message.lower():
            return "connection_error"
        elif "timeout" in error_message.lower():
            return "timeout_error"
        elif "memory" in error_message.lower():
            return "memory_error"
        elif "api" in error_message.lower():
            return "api_error"
        elif error_type == "ValueError":
            return "value_error"
        elif error_type == "KeyError":
            return "key_error"
        else:
            return f"{error_type}_general"
    
    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Obtém estatísticas de recuperação"""
        stats = {}
        
        for pattern, results in self.recovery_success_rate.items():
            if results:
                success_rate = sum(results) / len(results) * 100
                stats[pattern] = {
                    'attempts': len(results),
                    'success_rate': success_rate,
                    'recent_success': results[-5:] if len(results) >= 5 else results
                }
        
        return stats

class RobustnessEnhancer:
    """Sistema principal de aprimoramento de robustez"""
    
    def __init__(self, config: RobustnessConfig = None):
        self.config = config or RobustnessConfig()
        
        # Componentes
        self.regime_detector = MarketRegimeDetector(self.config)
        self.risk_manager = AdaptiveRiskManager(self.config)
        self.error_recovery = ErrorRecoverySystem()
        
        # Estado
        self.current_market_condition = None
        self.system_health = {}
        
        # Configurar estratégias de recuperação
        self._setup_recovery_strategies()
    
    def _setup_recovery_strategies(self):
        """Configura estratégias de recuperação"""
        
        async def connection_recovery(error: Exception, context: Dict[str, Any]) -> bool:
            """Recuperação de erro de conexão"""
            logger.info("Tentando recuperar conexão...")
            await asyncio.sleep(5)  # Aguardar
            # Aqui seria implementada reconexão específica
            return True
        
        async def memory_recovery(error: Exception, context: Dict[str, Any]) -> bool:
            """Recuperação de erro de memória"""
            logger.info("Liberando memória...")
            import gc
            gc.collect()
            return True
        
        async def api_recovery(error: Exception, context: Dict[str, Any]) -> bool:
            """Recuperação de erro de API"""
            logger.info("Aguardando antes de tentar API novamente...")
            await asyncio.sleep(10)
            return True
        
        # Registrar estratégias
        self.error_recovery.register_recovery_strategy("connection_error", connection_recovery)
        self.error_recovery.register_recovery_strategy("memory_error", memory_recovery)
        self.error_recovery.register_recovery_strategy("api_error", api_recovery)
    
    @debug_function
    async def enhance_trading_decision(self, symbol: str, signal: Dict[str, Any], 
                                     market_data: pd.DataFrame) -> Dict[str, Any]:
        """Aprimora decisão de trading com robustez"""
        try:
            with debug_context(symbol=symbol, action=signal.get('action')):
                # Detectar regime de mercado
                market_condition = await self.regime_detector.detect_regime(market_data)
                self.current_market_condition = market_condition
                
                # Avaliar viabilidade do trade
                viability = await self.risk_manager.assess_trade_viability(
                    symbol, signal, market_condition
                )
                
                if not viability['approved']:
                    return {
                        'action': 'hold',
                        'reason': viability['reason'],
                        'original_signal': signal,
                        'market_condition': market_condition,
                        'viability_assessment': viability
                    }
                
                # Aprimorar sinal com informações de robustez
                enhanced_signal = {
                    'action': signal['action'],
                    'confidence': signal.get('confidence', 0.0),
                    'position_size': viability['position_size'],
                    'stop_loss': viability['stop_loss'],
                    'market_regime': market_condition.regime.value,
                    'risk_level': market_condition.risk_level.value,
                    'signal_quality': viability['signal_quality'],
                    'original_signal': signal,
                    'robustness_score': self._calculate_robustness_score(signal, market_condition)
                }
                
                return enhanced_signal
                
        except Exception as e:
            logger.error(f"Erro no aprimoramento de decisão: {e}")
            
            # Tentar recuperação
            recovery_success = await self.error_recovery.handle_error(e, {
                'function': 'enhance_trading_decision',
                'symbol': symbol,
                'signal': signal
            })
            
            if recovery_success:
                # Tentar novamente
                return await self.enhance_trading_decision(symbol, signal, market_data)
            
            # Fallback seguro
            return {
                'action': 'hold',
                'reason': 'error_in_enhancement',
                'error': str(e),
                'original_signal': signal
            }
    
    def _calculate_robustness_score(self, signal: Dict[str, Any], 
                                   market_condition: MarketCondition) -> float:
        """Calcula score de robustez"""
        score = 0.0
        
        # Componente de confiança do sinal
        confidence = signal.get('confidence', 0.0)
        score += confidence * 0.3
        
        # Componente de adequação ao regime
        regime_adequacy = self.risk_manager._assess_regime_adequacy(signal, market_condition)
        score += regime_adequacy * 0.3
        
        # Componente de qualidade do mercado
        market_quality = (market_condition.liquidity_score + 
                         (1.0 - min(market_condition.volatility, 1.0))) / 2
        score += market_quality * 0.2
        
        # Componente de confiança na detecção de regime
        score += market_condition.confidence * 0.2
        
        return score
    
    async def record_trade_outcome(self, symbol: str, pnl: float):
        """Registra resultado de trade"""
        if self.current_market_condition:
            self.risk_manager.record_trade_result(symbol, pnl, self.current_market_condition)
    
    def get_system_health(self) -> Dict[str, Any]:
        """Obtém saúde do sistema"""
        return {
            'current_market_condition': asdict(self.current_market_condition) if self.current_market_condition else None,
            'circuit_breaker_active': self.risk_manager.circuit_breaker_active,
            'daily_trade_count': self.risk_manager.daily_trade_count,
            'adaptive_parameters': self.risk_manager.adaptive_params,
            'recovery_statistics': self.error_recovery.get_recovery_statistics(),
            'regime_history_length': len(self.regime_detector.regime_history)
        }

# Instância global
robustness_enhancer: Optional[RobustnessEnhancer] = None

def initialize_robustness_system(config: RobustnessConfig = None) -> RobustnessEnhancer:
    """Inicializa sistema de robustez global"""
    global robustness_enhancer
    robustness_enhancer = RobustnessEnhancer(config)
    return robustness_enhancer

def get_robustness_system() -> Optional[RobustnessEnhancer]:
    """Obtém sistema de robustez global"""
    return robustness_enhancer

if __name__ == "__main__":
    # Exemplo de uso
    async def main():
        # Configurar sistema
        config = RobustnessConfig(
            enable_dynamic_adaptation=True,
            max_position_size_normal=0.1,
            circuit_breaker_threshold=0.05
        )
        
        enhancer = initialize_robustness_system(config)
        
        # Simular dados de mercado
        dates = pd.date_range(start='2023-01-01', periods=100, freq='H')
        prices = 100 + np.cumsum(np.random.randn(100) * 0.01)
        volumes = np.random.randint(1000, 10000, 100)
        
        market_data = pd.DataFrame({
            'timestamp': dates,
            'close': prices,
            'high': prices * 1.01,
            'low': prices * 0.99,
            'volume': volumes
        })
        
        # Simular sinal
        signal = {
            'action': 'buy',
            'confidence': 0.7,
            'scores': {
                'ai': 0.8,
                'quantum': 0.6,
                'technical': 0.7
            }
        }
        
        # Aprimorar decisão
        enhanced_signal = await enhancer.enhance_trading_decision('BTCUSDT', signal, market_data)
        
        print("Sinal aprimorado:")
        print(json.dumps(enhanced_signal, indent=2, default=str))
        
        # Simular resultado
        await enhancer.record_trade_outcome('BTCUSDT', 0.02)  # 2% profit
        
        # Verificar saúde do sistema
        health = enhancer.get_system_health()
        print("\nSaúde do sistema:")
        print(json.dumps(health, indent=2, default=str))
    
    # Executar exemplo
    # asyncio.run(main())

