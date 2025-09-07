"""
Gerenciador de Estratégias - RoboTrader
Versão corrigida e robusta para substituir arquivo corrompido
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging
import json

from utils import setup_logging

logger = setup_logging(__name__)

class SignalType(Enum):
    """Tipos de sinais de trading"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class StrategyType(Enum):
    """Tipos de estratégias disponíveis"""
    AI_HYBRID = "ai_hybrid"
    QUANTUM = "quantum"
    NEWS_SENTIMENT = "news_sentiment"
    TECHNICAL = "technical"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"

@dataclass
class TradingSignal:
    """Estrutura de um sinal de trading"""
    strategy: StrategyType
    signal: SignalType
    confidence: float  # 0.0 - 1.0
    strength: float    # 0.0 - 1.0
    timestamp: datetime
    symbol: str
    price: float
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        """Converte para dicionário"""
        return {
            'strategy': self.strategy.value,
            'signal': self.signal.value,
            'confidence': self.confidence,
            'strength': self.strength,
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'price': self.price,
            'metadata': self.metadata
        }

@dataclass
class StrategyConfig:
    """Configuração de uma estratégia"""
    name: str
    enabled: bool
    weight: float  # Peso na decisão final (0.0 - 1.0)
    min_confidence: float  # Confiança mínima para considerar sinal
    cooldown_minutes: int  # Tempo mínimo entre sinais
    parameters: Dict[str, Any]

class StrategyManager:
    """
    Gerenciador Central de Estratégias de Trading
    
    Funcionalidades:
    - Combinação inteligente de múltiplos sinais
    - Ponderação dinâmica por performance
    - Filtragem por confiança e força
    - Análise de consenso
    - Backtesting de estratégias
    - Métricas de performance por estratégia
    """
    
    def __init__(self):
        self.strategies = self._initialize_strategies()
        self.signal_history = []
        self.performance_metrics = {}
        self.last_signals = {}  # Para cooldown
        
        # Configurações de combinação
        self.consensus_threshold = 0.6  # 60% de consenso mínimo
        self.max_signals_history = 1000
        
        # Pesos adaptativos (atualizados por performance)
        self.adaptive_weights = {
            StrategyType.AI_HYBRID: 0.35,
            StrategyType.QUANTUM: 0.20,
            StrategyType.NEWS_SENTIMENT: 0.15,
            StrategyType.TECHNICAL: 0.15,
            StrategyType.MOMENTUM: 0.10,
            StrategyType.MEAN_REVERSION: 0.05
        }
        
        logger.info("StrategyManager inicializado com {} estratégias".format(len(self.strategies)))
    
    def _initialize_strategies(self) -> Dict[StrategyType, StrategyConfig]:
        """Inicializa configurações das estratégias"""
        return {
            StrategyType.AI_HYBRID: StrategyConfig(
                name="IA Híbrida (CNN+LSTM+Transformer)",
                enabled=True,
                weight=0.35,
                min_confidence=0.6,
                cooldown_minutes=5,
                parameters={
                    'sequence_length': 60,
                    'prediction_horizon': 1,
                    'ensemble_models': 3
                }
            ),
            StrategyType.QUANTUM: StrategyConfig(
                name="Análise Quântica",
                enabled=True,
                weight=0.20,
                min_confidence=0.5,
                cooldown_minutes=10,
                parameters={
                    'n_qubits': 8,
                    'measurement_shots': 1000,
                    'entanglement_depth': 3
                }
            ),
            StrategyType.NEWS_SENTIMENT: StrategyConfig(
                name="Sentimento de Notícias",
                enabled=True,
                weight=0.15,
                min_confidence=0.4,
                cooldown_minutes=15,
                parameters={
                    'sentiment_threshold': 0.3,
                    'news_sources': ['finnhub', 'alpha_vantage'],
                    'lookback_hours': 24
                }
            ),
            StrategyType.TECHNICAL: StrategyConfig(
                name="Análise Técnica",
                enabled=True,
                weight=0.15,
                min_confidence=0.5,
                cooldown_minutes=3,
                parameters={
                    'indicators': ['RSI', 'MACD', 'BB', 'EMA'],
                    'timeframes': ['5m', '15m', '1h'],
                    'confirmation_required': 2
                }
            ),
            StrategyType.MOMENTUM: StrategyConfig(
                name="Momentum",
                enabled=True,
                weight=0.10,
                min_confidence=0.6,
                cooldown_minutes=5,
                parameters={
                    'lookback_periods': [10, 20, 50],
                    'momentum_threshold': 0.02,
                    'volume_confirmation': True
                }
            ),
            StrategyType.MEAN_REVERSION: StrategyConfig(
                name="Reversão à Média",
                enabled=False,  # Desabilitada por padrão em mercados trending
                weight=0.05,
                min_confidence=0.7,
                cooldown_minutes=30,
                parameters={
                    'deviation_threshold': 2.0,
                    'lookback_window': 100,
                    'reversion_target': 0.5
                }
            )
        }
    
    def add_signal(self, signal: TradingSignal) -> bool:
        """
        Adiciona um novo sinal ao histórico
        
        Args:
            signal: Sinal de trading a ser adicionado
            
        Returns:
            bool: True se sinal foi aceito, False se rejeitado
        """
        try:
            # Verificar se estratégia está habilitada
            strategy_config = self.strategies.get(signal.strategy)
            if not strategy_config or not strategy_config.enabled:
                logger.debug(f"Estratégia {signal.strategy.value} desabilitada, sinal rejeitado")
                return False
            
            # Verificar confiança mínima
            if signal.confidence < strategy_config.min_confidence:
                logger.debug(f"Confiança {signal.confidence:.2f} abaixo do mínimo {strategy_config.min_confidence:.2f}")
                return False
            
            # Verificar cooldown
            if self._is_in_cooldown(signal.strategy, signal.symbol):
                logger.debug(f"Estratégia {signal.strategy.value} em cooldown para {signal.symbol}")
                return False
            
            # Adicionar ao histórico
            self.signal_history.append(signal)
            
            # Manter tamanho do histórico
            if len(self.signal_history) > self.max_signals_history:
                self.signal_history = self.signal_history[-self.max_signals_history:]
            
            # Atualizar último sinal
            key = f"{signal.strategy.value}_{signal.symbol}"
            self.last_signals[key] = signal.timestamp
            
            logger.debug(f"Sinal adicionado: {signal.strategy.value} {signal.signal.value} "
                        f"conf={signal.confidence:.2f} para {signal.symbol}")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao adicionar sinal: {e}")
            return False
    
    def _is_in_cooldown(self, strategy: StrategyType, symbol: str) -> bool:
        """Verifica se estratégia está em cooldown para o símbolo"""
        key = f"{strategy.value}_{symbol}"
        
        if key not in self.last_signals:
            return False
        
        last_signal_time = self.last_signals[key]
        cooldown_minutes = self.strategies[strategy].cooldown_minutes
        
        elapsed = datetime.now() - last_signal_time
        return elapsed.total_seconds() < (cooldown_minutes * 60)
    
    def get_combined_signal(self, symbol: str, lookback_minutes: int = 30) -> Optional[TradingSignal]:
        """
        Combina sinais recentes para gerar decisão final
        
        Args:
            symbol: Símbolo para análise
            lookback_minutes: Janela de tempo para considerar sinais
            
        Returns:
            TradingSignal combinado ou None se não há consenso
        """
        try:
            # Filtrar sinais recentes para o símbolo
            cutoff_time = datetime.now() - timedelta(minutes=lookback_minutes)
            recent_signals = [
                s for s in self.signal_history 
                if s.symbol == symbol and s.timestamp >= cutoff_time
            ]
            
            if not recent_signals:
                logger.debug(f"Nenhum sinal recente para {symbol}")
                return None
            
            # Agrupar por tipo de sinal
            signal_groups = {
                SignalType.BUY: [],
                SignalType.SELL: [],
                SignalType.HOLD: []
            }
            
            for signal in recent_signals:
                signal_groups[signal.signal].append(signal)
            
            # Calcular scores ponderados para cada tipo de sinal
            signal_scores = {}
            
            for signal_type, signals in signal_groups.items():
                if not signals:
                    signal_scores[signal_type] = 0.0
                    continue
                
                total_score = 0.0
                total_weight = 0.0
                
                for signal in signals:
                    strategy_weight = self.adaptive_weights.get(signal.strategy, 0.1)
                    confidence_weight = signal.confidence
                    strength_weight = signal.strength
                    
                    # Score combinado: peso da estratégia × confiança × força
                    score = strategy_weight * confidence_weight * strength_weight
                    total_score += score
                    total_weight += strategy_weight
                
                # Normalizar pelo peso total
                signal_scores[signal_type] = total_score / max(total_weight, 0.001)
            
            # Determinar sinal vencedor
            winning_signal = max(signal_scores.keys(), key=lambda k: signal_scores[k])
            winning_score = signal_scores[winning_signal]
            
            # Verificar se atende threshold de consenso
            if winning_score < self.consensus_threshold:
                logger.debug(f"Score {winning_score:.2f} abaixo do threshold {self.consensus_threshold}")
                return None
            
            # Calcular confiança e força combinadas
            combined_confidence = min(winning_score, 1.0)
            
            # Calcular força baseada na diferença entre sinais
            signal_values = list(signal_scores.values())
            signal_values.sort(reverse=True)
            
            if len(signal_values) > 1:
                strength_ratio = (signal_values[0] - signal_values[1]) / max(signal_values[0], 0.001)
                combined_strength = min(strength_ratio, 1.0)
            else:
                combined_strength = combined_confidence
            
            # Obter preço mais recente
            latest_signal = max(recent_signals, key=lambda s: s.timestamp)
            current_price = latest_signal.price
            
            # Criar metadados
            metadata = {
                'signals_count': len(recent_signals),
                'buy_score': signal_scores[SignalType.BUY],
                'sell_score': signal_scores[SignalType.SELL],
                'hold_score': signal_scores[SignalType.HOLD],
                'consensus_ratio': winning_score,
                'strategies_involved': list(set(s.strategy.value for s in recent_signals)),
                'lookback_minutes': lookback_minutes
            }
            
            # Criar sinal combinado
            combined_signal = TradingSignal(
                strategy=StrategyType.AI_HYBRID,  # Representativo
                signal=winning_signal,
                confidence=combined_confidence,
                strength=combined_strength,
                timestamp=datetime.now(),
                symbol=symbol,
                price=current_price,
                metadata=metadata
            )
            
            logger.info(f"Sinal combinado para {symbol}: {winning_signal.value} "
                       f"(conf={combined_confidence:.2f}, força={combined_strength:.2f})")
            
            return combined_signal
            
        except Exception as e:
            logger.error(f"Erro ao combinar sinais: {e}")
            return None
    
    def analyze_consensus(self, symbol: str, lookback_minutes: int = 60) -> Dict[str, Any]:
        """
        Analisa consenso entre estratégias
        
        Args:
            symbol: Símbolo para análise
            lookback_minutes: Janela de tempo
            
        Returns:
            Dicionário com análise de consenso
        """
        try:
            cutoff_time = datetime.now() - timedelta(minutes=lookback_minutes)
            recent_signals = [
                s for s in self.signal_history 
                if s.symbol == symbol and s.timestamp >= cutoff_time
            ]
            
            if not recent_signals:
                return {
                    'consensus_level': 0.0,
                    'dominant_signal': 'hold',
                    'agreement_ratio': 0.0,
                    'strategies_count': 0,
                    'signals_count': 0
                }
            
            # Contar sinais por tipo
            signal_counts = {
                'buy': len([s for s in recent_signals if s.signal == SignalType.BUY]),
                'sell': len([s for s in recent_signals if s.signal == SignalType.SELL]),
                'hold': len([s for s in recent_signals if s.signal == SignalType.HOLD])
            }
            
            total_signals = sum(signal_counts.values())
            dominant_signal = max(signal_counts.keys(), key=lambda k: signal_counts[k])
            agreement_ratio = signal_counts[dominant_signal] / max(total_signals, 1)
            
            # Calcular nível de consenso (ponderado por confiança)
            weighted_scores = {'buy': 0.0, 'sell': 0.0, 'hold': 0.0}
            total_weight = 0.0
            
            for signal in recent_signals:
                weight = signal.confidence * self.adaptive_weights.get(signal.strategy, 0.1)
                weighted_scores[signal.signal.value] += weight
                total_weight += weight
            
            if total_weight > 0:
                for key in weighted_scores:
                    weighted_scores[key] /= total_weight
            
            consensus_level = max(weighted_scores.values())
            
            # Estratégias únicas envolvidas
            unique_strategies = set(s.strategy.value for s in recent_signals)
            
            return {
                'consensus_level': consensus_level,
                'dominant_signal': dominant_signal,
                'agreement_ratio': agreement_ratio,
                'strategies_count': len(unique_strategies),
                'signals_count': total_signals,
                'signal_distribution': signal_counts,
                'weighted_scores': weighted_scores,
                'strategies_involved': list(unique_strategies)
            }
            
        except Exception as e:
            logger.error(f"Erro na análise de consenso: {e}")
            return {}
    
    def update_strategy_performance(self, strategy: StrategyType, 
                                  performance_score: float, trade_result: float):
        """
        Atualiza performance de uma estratégia e ajusta pesos
        
        Args:
            strategy: Tipo da estratégia
            performance_score: Score de performance (0.0 - 1.0)
            trade_result: Resultado do trade (PnL normalizado)
        """
        try:
            if strategy not in self.performance_metrics:
                self.performance_metrics[strategy] = {
                    'total_trades': 0,
                    'successful_trades': 0,
                    'total_pnl': 0.0,
                    'avg_performance': 0.5,
                    'last_update': datetime.now()
                }
            
            metrics = self.performance_metrics[strategy]
            
            # Atualizar métricas
            metrics['total_trades'] += 1
            if trade_result > 0:
                metrics['successful_trades'] += 1
            metrics['total_pnl'] += trade_result
            
            # Calcular nova performance média (com decay)
            decay_factor = 0.9  # Dar mais peso a resultados recentes
            metrics['avg_performance'] = (
                metrics['avg_performance'] * decay_factor + 
                performance_score * (1 - decay_factor)
            )
            
            metrics['last_update'] = datetime.now()
            
            # Ajustar peso adaptativo
            self._update_adaptive_weights()
            
            logger.debug(f"Performance atualizada para {strategy.value}: "
                        f"score={performance_score:.2f}, pnl={trade_result:.4f}")
            
        except Exception as e:
            logger.error(f"Erro ao atualizar performance: {e}")
    
    def _update_adaptive_weights(self):
        """Atualiza pesos adaptativos baseado na performance"""
        try:
            if not self.performance_metrics:
                return
            
            # Calcular scores normalizados
            performance_scores = {}
            for strategy, metrics in self.performance_metrics.items():
                win_rate = metrics['successful_trades'] / max(metrics['total_trades'], 1)
                avg_performance = metrics['avg_performance']
                
                # Score combinado: win rate + performance média
                combined_score = (win_rate * 0.6 + avg_performance * 0.4)
                performance_scores[strategy] = combined_score
            
            # Normalizar scores para somar 1.0
            total_score = sum(performance_scores.values())
            if total_score > 0:
                for strategy in performance_scores:
                    normalized_score = performance_scores[strategy] / total_score
                    
                    # Aplicar suavização para evitar mudanças bruscas
                    current_weight = self.adaptive_weights.get(strategy, 0.1)
                    smoothing_factor = 0.8
                    
                    new_weight = (
                        current_weight * smoothing_factor + 
                        normalized_score * (1 - smoothing_factor)
                    )
                    
                    self.adaptive_weights[strategy] = new_weight
            
            logger.debug("Pesos adaptativos atualizados: " + 
                        str({k.value: f"{v:.3f}" for k, v in self.adaptive_weights.items()}))
            
        except Exception as e:
            logger.error(f"Erro ao atualizar pesos adaptativos: {e}")
    
    def get_strategy_metrics(self) -> Dict[str, Any]:
        """Retorna métricas detalhadas das estratégias"""
        try:
            metrics = {
                'adaptive_weights': {k.value: v for k, v in self.adaptive_weights.items()},
                'strategy_configs': {
                    k.value: {
                        'enabled': v.enabled,
                        'weight': v.weight,
                        'min_confidence': v.min_confidence,
                        'cooldown_minutes': v.cooldown_minutes
                    } for k, v in self.strategies.items()
                },
                'performance_metrics': {},
                'signal_statistics': {
                    'total_signals': len(self.signal_history),
                    'signals_last_hour': len([
                        s for s in self.signal_history 
                        if s.timestamp >= datetime.now() - timedelta(hours=1)
                    ]),
                    'signals_last_day': len([
                        s for s in self.signal_history 
                        if s.timestamp >= datetime.now() - timedelta(days=1)
                    ])
                }
            }
            
            # Adicionar métricas de performance
            for strategy, perf in self.performance_metrics.items():
                win_rate = perf['successful_trades'] / max(perf['total_trades'], 1) * 100
                
                metrics['performance_metrics'][strategy.value] = {
                    'total_trades': perf['total_trades'],
                    'win_rate': win_rate,
                    'total_pnl': perf['total_pnl'],
                    'avg_performance': perf['avg_performance'],
                    'last_update': perf['last_update'].isoformat()
                }
            
            return metrics
            
        except Exception as e:
            logger.error(f"Erro ao obter métricas: {e}")
            return {}
    
    def enable_strategy(self, strategy: StrategyType, enabled: bool = True):
        """Habilita/desabilita uma estratégia"""
        if strategy in self.strategies:
            self.strategies[strategy].enabled = enabled
            logger.info(f"Estratégia {strategy.value} {'habilitada' if enabled else 'desabilitada'}")
    
    def set_strategy_weight(self, strategy: StrategyType, weight: float):
        """Define peso de uma estratégia"""
        if strategy in self.strategies and 0.0 <= weight <= 1.0:
            self.strategies[strategy].weight = weight
            logger.info(f"Peso da estratégia {strategy.value} definido para {weight:.2f}")
    
    def clear_signal_history(self):
        """Limpa histórico de sinais"""
        self.signal_history.clear()
        self.last_signals.clear()
        logger.info("Histórico de sinais limpo")

# Instância global
strategy_manager = StrategyManager()

