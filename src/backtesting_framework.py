"""
Framework de Backtesting Avançado - RoboTrader
Sistema completo para simulações históricas e validação de estratégias.
"""

import os
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple, Callable
from dataclasses import dataclass, asdict, field
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing as mp
from functools import partial
import warnings
warnings.filterwarnings('ignore')

# Análise e visualização
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.offline as pyo

# Análise financeira
import yfinance as yf
import pandas_ta as ta
from scipy import stats
import quantstats as qs
import empyrical as emp
import pyfolio as pf

# Machine Learning
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.model_selection import TimeSeriesSplit
import joblib

# Importações locais
from config import config
from utils import setup_logging
from database_migration import RobustDatabaseManager
from ai_model import AIModel
from quantum_analyzer import QuantumAnalyzer
from news_analyzer import NewsAnalyzer
from risk_manager import RiskManager
from trade_executor import TradeExecutor

logger = setup_logging(__name__)

@dataclass
class BacktestConfig:
    """Configuração do backtesting"""
    # Período de teste
    start_date: datetime
    end_date: datetime
    
    # Configurações de capital
    initial_capital: float = 100000.0
    max_position_size: float = 0.1  # 10% do capital por posição
    commission: float = 0.001  # 0.1% de comissão
    slippage: float = 0.0005  # 0.05% de slippage
    
    # Configurações de dados
    symbols: List[str] = field(default_factory=lambda: ['BTCUSDT', 'ETHUSDT'])
    timeframes: List[str] = field(default_factory=lambda: ['1h', '4h', '1d'])
    
    # Configurações de estratégia
    strategy_weights: Dict[str, float] = field(default_factory=lambda: {
        'ai_model': 0.4,
        'quantum_analysis': 0.3,
        'technical_analysis': 0.2,
        'news_sentiment': 0.1
    })
    
    # Configurações de risco
    max_drawdown: float = 0.2  # 20% máximo drawdown
    stop_loss: float = 0.05  # 5% stop loss
    take_profit: float = 0.15  # 15% take profit
    
    # Configurações de execução
    parallel_processing: bool = True
    num_workers: int = mp.cpu_count() - 1
    chunk_size: int = 1000
    
    # Configurações de output
    save_results: bool = True
    generate_plots: bool = True
    detailed_logs: bool = False

@dataclass
class Trade:
    """Representação de um trade"""
    timestamp: datetime
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: float
    price: float
    commission: float
    slippage: float
    
    # Metadados da decisão
    ai_confidence: float = 0.0
    quantum_score: float = 0.0
    technical_score: float = 0.0
    news_sentiment: float = 0.0
    risk_score: float = 0.0
    
    # Resultado do trade
    pnl: float = 0.0
    pnl_percentage: float = 0.0
    duration: Optional[timedelta] = None
    exit_reason: str = ""

@dataclass
class Position:
    """Representação de uma posição"""
    symbol: str
    side: str
    quantity: float
    entry_price: float
    entry_time: datetime
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None

@dataclass
class BacktestResults:
    """Resultados do backtesting"""
    # Configuração
    config: BacktestConfig
    
    # Métricas básicas
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    # Métricas financeiras
    initial_capital: float = 0.0
    final_capital: float = 0.0
    total_return: float = 0.0
    total_return_percentage: float = 0.0
    
    # Métricas de risco
    max_drawdown: float = 0.0
    max_drawdown_percentage: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    # Métricas de performance
    average_trade_return: float = 0.0
    average_winning_trade: float = 0.0
    average_losing_trade: float = 0.0
    largest_winning_trade: float = 0.0
    largest_losing_trade: float = 0.0
    
    # Dados detalhados
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    daily_returns: pd.Series = field(default_factory=pd.Series)
    
    # Análise por símbolo
    symbol_performance: Dict[str, Dict[str, float]] = field(default_factory=dict)
    
    # Análise temporal
    monthly_returns: pd.Series = field(default_factory=pd.Series)
    yearly_returns: pd.Series = field(default_factory=pd.Series)
    
    # Métricas avançadas
    value_at_risk_95: float = 0.0
    conditional_var_95: float = 0.0
    maximum_consecutive_losses: int = 0
    maximum_consecutive_wins: int = 0
    
    # Tempo de execução
    execution_time: float = 0.0
    
    # Metadados
    timestamp: datetime = field(default_factory=datetime.now)

class DataProvider:
    """Provedor de dados para backtesting"""
    
    def __init__(self, db_manager: Optional[RobustDatabaseManager] = None):
        self.db_manager = db_manager
        self.cache = {}
    
    async def get_historical_data(self, symbol: str, timeframe: str, 
                                 start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Obtém dados históricos"""
        cache_key = f"{symbol}_{timeframe}_{start_date}_{end_date}"
        
        if cache_key in self.cache:
            return self.cache[cache_key].copy()
        
        try:
            # Tentar obter do banco de dados primeiro
            if self.db_manager:
                data = await self.db_manager.get_market_data(symbol, timeframe, start_date, end_date)
                if not data.empty:
                    self.cache[cache_key] = data
                    return data.copy()
            
            # Fallback para yfinance
            logger.info(f"Obtendo dados do yfinance para {symbol}")
            ticker = yf.Ticker(symbol.replace('USDT', '-USD'))
            
            # Mapear timeframes
            interval_map = {
                '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
                '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '8h': '8h', '12h': '12h',
                '1d': '1d', '3d': '3d', '1w': '1wk', '1M': '1mo'
            }
            
            interval = interval_map.get(timeframe, '1h')
            
            data = ticker.history(
                start=start_date,
                end=end_date,
                interval=interval,
                auto_adjust=True,
                prepost=True
            )
            
            if data.empty:
                logger.warning(f"Nenhum dado encontrado para {symbol}")
                return pd.DataFrame()
            
            # Padronizar colunas
            data = data.rename(columns={
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            
            data.reset_index(inplace=True)
            data.rename(columns={'Date': 'timestamp'}, inplace=True)
            
            # Adicionar indicadores técnicos
            data = self._add_technical_indicators(data)
            
            self.cache[cache_key] = data
            return data.copy()
            
        except Exception as e:
            logger.error(f"Erro ao obter dados para {symbol}: {e}")
            return pd.DataFrame()
    
    def _add_technical_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Adiciona indicadores técnicos aos dados"""
        try:
            # RSI
            data['rsi'] = ta.rsi(data['close'], length=14)
            
            # MACD
            macd = ta.macd(data['close'])
            data['macd'] = macd['MACD_12_26_9']
            data['macd_signal'] = macd['MACDs_12_26_9']
            data['macd_histogram'] = macd['MACDh_12_26_9']
            
            # Bollinger Bands
            bb = ta.bbands(data['close'], length=20)
            data['bb_upper'] = bb['BBU_20_2.0']
            data['bb_middle'] = bb['BBM_20_2.0']
            data['bb_lower'] = bb['BBL_20_2.0']
            
            # Moving Averages
            data['sma_20'] = ta.sma(data['close'], length=20)
            data['sma_50'] = ta.sma(data['close'], length=50)
            data['ema_12'] = ta.ema(data['close'], length=12)
            data['ema_26'] = ta.ema(data['close'], length=26)
            
            # Volume indicators
            data['volume_sma'] = ta.sma(data['volume'], length=20)
            data['vwap'] = ta.vwap(data['high'], data['low'], data['close'], data['volume'])
            
            # Volatility
            data['atr'] = ta.atr(data['high'], data['low'], data['close'], length=14)
            
            # Momentum
            data['momentum'] = ta.mom(data['close'], length=10)
            data['roc'] = ta.roc(data['close'], length=10)
            
            return data
            
        except Exception as e:
            logger.error(f"Erro ao adicionar indicadores técnicos: {e}")
            return data

class StrategyEngine:
    """Engine de estratégias para backtesting"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.ai_model = None
        self.quantum_analyzer = None
        self.news_analyzer = None
        self.risk_manager = None
        
        # Inicializar componentes
        self._initialize_components()
    
    def _initialize_components(self):
        """Inicializa componentes da estratégia"""
        try:
            # Inicializar com configurações de backtesting
            self.ai_model = AIModel(mode='backtest')
            self.quantum_analyzer = QuantumAnalyzer(mode='backtest')
            self.news_analyzer = NewsAnalyzer(mode='backtest')
            self.risk_manager = RiskManager(mode='backtest')
            
        except Exception as e:
            logger.error(f"Erro ao inicializar componentes: {e}")
    
    async def generate_signal(self, symbol: str, data: pd.DataFrame, 
                            current_time: datetime) -> Dict[str, Any]:
        """Gera sinal de trading"""
        try:
            # Obter dados até o momento atual
            current_data = data[data['timestamp'] <= current_time].copy()
            
            if len(current_data) < 50:  # Dados insuficientes
                return {'action': 'hold', 'confidence': 0.0, 'scores': {}}
            
            # Análise de IA
            ai_signal = await self._get_ai_signal(symbol, current_data)
            
            # Análise quântica
            quantum_signal = await self._get_quantum_signal(symbol, current_data)
            
            # Análise técnica
            technical_signal = self._get_technical_signal(current_data)
            
            # Análise de sentimento (simulada para backtesting)
            news_signal = await self._get_news_signal(symbol, current_time)
            
            # Análise de risco
            risk_signal = await self._get_risk_signal(symbol, current_data)
            
            # Combinar sinais
            combined_signal = self._combine_signals({
                'ai': ai_signal,
                'quantum': quantum_signal,
                'technical': technical_signal,
                'news': news_signal,
                'risk': risk_signal
            })
            
            return combined_signal
            
        except Exception as e:
            logger.error(f"Erro ao gerar sinal para {symbol}: {e}")
            return {'action': 'hold', 'confidence': 0.0, 'scores': {}}
    
    async def _get_ai_signal(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """Obtém sinal do modelo de IA"""
        try:
            if self.ai_model is None:
                return {'action': 'hold', 'confidence': 0.0}
            
            # Preparar features
            features = self._prepare_features(data)
            
            # Fazer predição
            prediction = await self.ai_model.predict(features)
            
            return {
                'action': prediction.get('action', 'hold'),
                'confidence': prediction.get('confidence', 0.0),
                'price_prediction': prediction.get('price_prediction', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Erro na análise de IA: {e}")
            return {'action': 'hold', 'confidence': 0.0}
    
    async def _get_quantum_signal(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """Obtém sinal da análise quântica"""
        try:
            if self.quantum_analyzer is None:
                return {'action': 'hold', 'confidence': 0.0}
            
            # Análise quântica
            quantum_result = await self.quantum_analyzer.analyze(data)
            
            return {
                'action': quantum_result.get('action', 'hold'),
                'confidence': quantum_result.get('confidence', 0.0),
                'quantum_score': quantum_result.get('quantum_score', 0.0)
            }
            
        except Exception as e:
            logger.error(f"Erro na análise quântica: {e}")
            return {'action': 'hold', 'confidence': 0.0}
    
    def _get_technical_signal(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Obtém sinal da análise técnica"""
        try:
            latest = data.iloc[-1]
            
            signals = []
            
            # RSI
            if latest['rsi'] < 30:
                signals.append(('buy', 0.7))
            elif latest['rsi'] > 70:
                signals.append(('sell', 0.7))
            
            # MACD
            if latest['macd'] > latest['macd_signal'] and data.iloc[-2]['macd'] <= data.iloc[-2]['macd_signal']:
                signals.append(('buy', 0.6))
            elif latest['macd'] < latest['macd_signal'] and data.iloc[-2]['macd'] >= data.iloc[-2]['macd_signal']:
                signals.append(('sell', 0.6))
            
            # Bollinger Bands
            if latest['close'] < latest['bb_lower']:
                signals.append(('buy', 0.5))
            elif latest['close'] > latest['bb_upper']:
                signals.append(('sell', 0.5))
            
            # Moving Average Crossover
            if latest['ema_12'] > latest['ema_26'] and data.iloc[-2]['ema_12'] <= data.iloc[-2]['ema_26']:
                signals.append(('buy', 0.6))
            elif latest['ema_12'] < latest['ema_26'] and data.iloc[-2]['ema_12'] >= data.iloc[-2]['ema_26']:
                signals.append(('sell', 0.6))
            
            # Combinar sinais técnicos
            if not signals:
                return {'action': 'hold', 'confidence': 0.0}
            
            buy_signals = [conf for action, conf in signals if action == 'buy']
            sell_signals = [conf for action, conf in signals if action == 'sell']
            
            if buy_signals and not sell_signals:
                return {'action': 'buy', 'confidence': np.mean(buy_signals)}
            elif sell_signals and not buy_signals:
                return {'action': 'sell', 'confidence': np.mean(sell_signals)}
            elif buy_signals and sell_signals:
                buy_strength = np.mean(buy_signals)
                sell_strength = np.mean(sell_signals)
                if buy_strength > sell_strength:
                    return {'action': 'buy', 'confidence': buy_strength - sell_strength}
                else:
                    return {'action': 'sell', 'confidence': sell_strength - buy_strength}
            else:
                return {'action': 'hold', 'confidence': 0.0}
                
        except Exception as e:
            logger.error(f"Erro na análise técnica: {e}")
            return {'action': 'hold', 'confidence': 0.0}
    
    async def _get_news_signal(self, symbol: str, current_time: datetime) -> Dict[str, Any]:
        """Obtém sinal de análise de notícias (simulado para backtesting)"""
        try:
            # Para backtesting, simular sentimento baseado em volatilidade histórica
            # Em produção, usaria dados reais de notícias
            
            # Simular sentimento neutro com pequenas variações
            sentiment = np.random.normal(0.0, 0.1)
            confidence = abs(sentiment) * 2  # Converter para confiança
            
            if sentiment > 0.1:
                action = 'buy'
            elif sentiment < -0.1:
                action = 'sell'
            else:
                action = 'hold'
            
            return {
                'action': action,
                'confidence': min(confidence, 1.0),
                'sentiment': sentiment
            }
            
        except Exception as e:
            logger.error(f"Erro na análise de notícias: {e}")
            return {'action': 'hold', 'confidence': 0.0}
    
    async def _get_risk_signal(self, symbol: str, data: pd.DataFrame) -> Dict[str, Any]:
        """Obtém sinal de análise de risco"""
        try:
            if self.risk_manager is None:
                return {'action': 'hold', 'confidence': 0.0}
            
            # Análise de risco
            risk_assessment = await self.risk_manager.assess_risk(symbol, data)
            
            return {
                'action': risk_assessment.get('action', 'hold'),
                'confidence': risk_assessment.get('confidence', 0.0),
                'risk_score': risk_assessment.get('risk_score', 0.5)
            }
            
        except Exception as e:
            logger.error(f"Erro na análise de risco: {e}")
            return {'action': 'hold', 'confidence': 0.0}
    
    def _combine_signals(self, signals: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Combina sinais de diferentes fontes"""
        try:
            weights = self.config.strategy_weights
            
            # Calcular score ponderado para cada ação
            buy_score = 0.0
            sell_score = 0.0
            hold_score = 0.0
            
            total_weight = 0.0
            
            for source, signal in signals.items():
                if source not in weights:
                    continue
                
                weight = weights[source]
                action = signal.get('action', 'hold')
                confidence = signal.get('confidence', 0.0)
                
                weighted_confidence = weight * confidence
                
                if action == 'buy':
                    buy_score += weighted_confidence
                elif action == 'sell':
                    sell_score += weighted_confidence
                else:
                    hold_score += weighted_confidence
                
                total_weight += weight
            
            # Normalizar scores
            if total_weight > 0:
                buy_score /= total_weight
                sell_score /= total_weight
                hold_score /= total_weight
            
            # Determinar ação final
            max_score = max(buy_score, sell_score, hold_score)
            
            if max_score == buy_score and buy_score > 0.3:
                final_action = 'buy'
                final_confidence = buy_score
            elif max_score == sell_score and sell_score > 0.3:
                final_action = 'sell'
                final_confidence = sell_score
            else:
                final_action = 'hold'
                final_confidence = hold_score
            
            return {
                'action': final_action,
                'confidence': final_confidence,
                'scores': {
                    'ai': signals.get('ai', {}).get('confidence', 0.0),
                    'quantum': signals.get('quantum', {}).get('confidence', 0.0),
                    'technical': signals.get('technical', {}).get('confidence', 0.0),
                    'news': signals.get('news', {}).get('confidence', 0.0),
                    'risk': signals.get('risk', {}).get('confidence', 0.0)
                },
                'buy_score': buy_score,
                'sell_score': sell_score,
                'hold_score': hold_score
            }
            
        except Exception as e:
            logger.error(f"Erro ao combinar sinais: {e}")
            return {'action': 'hold', 'confidence': 0.0, 'scores': {}}
    
    def _prepare_features(self, data: pd.DataFrame) -> np.ndarray:
        """Prepara features para o modelo de IA"""
        try:
            # Selecionar últimas N observações
            n_lookback = min(60, len(data))
            recent_data = data.tail(n_lookback)
            
            # Features básicas
            features = []
            
            # Preços normalizados
            close_prices = recent_data['close'].values
            close_normalized = (close_prices - close_prices.mean()) / close_prices.std()
            features.extend(close_normalized[-20:])  # Últimos 20 preços
            
            # Indicadores técnicos
            if 'rsi' in recent_data.columns:
                features.append(recent_data['rsi'].iloc[-1] / 100.0)
            
            if 'macd' in recent_data.columns:
                features.append(recent_data['macd'].iloc[-1])
            
            # Volume normalizado
            if 'volume' in recent_data.columns:
                volume = recent_data['volume'].values
                volume_normalized = (volume - volume.mean()) / volume.std()
                features.append(volume_normalized[-1])
            
            # Volatilidade
            returns = recent_data['close'].pct_change().dropna()
            if len(returns) > 0:
                features.append(returns.std())
            
            # Preencher com zeros se necessário
            while len(features) < 50:
                features.append(0.0)
            
            return np.array(features[:50])  # Limitar a 50 features
            
        except Exception as e:
            logger.error(f"Erro ao preparar features: {e}")
            return np.zeros(50)

class BacktestEngine:
    """Engine principal de backtesting"""
    
    def __init__(self, config: BacktestConfig, db_manager: Optional[RobustDatabaseManager] = None):
        self.config = config
        self.db_manager = db_manager
        self.data_provider = DataProvider(db_manager)
        self.strategy_engine = StrategyEngine(config)
        
        # Estado do backtesting
        self.current_capital = config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[Dict[str, Any]] = []
        
        # Métricas
        self.peak_capital = config.initial_capital
        self.max_drawdown = 0.0
    
    async def run_backtest(self) -> BacktestResults:
        """Executa o backtesting completo"""
        start_time = datetime.now()
        
        try:
            logger.info(f"🚀 Iniciando backtesting de {self.config.start_date} a {self.config.end_date}")
            
            # Obter dados históricos para todos os símbolos
            all_data = await self._load_historical_data()
            
            if not all_data:
                raise ValueError("Nenhum dado histórico encontrado")
            
            # Executar simulação
            await self._run_simulation(all_data)
            
            # Calcular métricas
            results = self._calculate_metrics()
            
            # Salvar resultados
            if self.config.save_results:
                await self._save_results(results)
            
            # Gerar gráficos
            if self.config.generate_plots:
                await self._generate_plots(results)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            results.execution_time = execution_time
            
            logger.info(f"✅ Backtesting concluído em {execution_time:.2f}s")
            logger.info(f"📊 Total de trades: {results.total_trades}")
            logger.info(f"💰 Retorno total: {results.total_return_percentage:.2f}%")
            logger.info(f"📈 Sharpe Ratio: {results.sharpe_ratio:.2f}")
            logger.info(f"📉 Max Drawdown: {results.max_drawdown_percentage:.2f}%")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Erro no backtesting: {e}")
            raise
    
    async def _load_historical_data(self) -> Dict[str, Dict[str, pd.DataFrame]]:
        """Carrega dados históricos para todos os símbolos e timeframes"""
        all_data = {}
        
        for symbol in self.config.symbols:
            all_data[symbol] = {}
            
            for timeframe in self.config.timeframes:
                logger.info(f"📥 Carregando dados: {symbol} {timeframe}")
                
                data = await self.data_provider.get_historical_data(
                    symbol, timeframe, self.config.start_date, self.config.end_date
                )
                
                if not data.empty:
                    all_data[symbol][timeframe] = data
                    logger.info(f"✅ {len(data)} registros carregados para {symbol} {timeframe}")
                else:
                    logger.warning(f"⚠️ Nenhum dado encontrado para {symbol} {timeframe}")
        
        return all_data
    
    async def _run_simulation(self, all_data: Dict[str, Dict[str, pd.DataFrame]]):
        """Executa a simulação de trading"""
        # Obter todas as timestamps únicas e ordenadas
        all_timestamps = set()
        
        for symbol_data in all_data.values():
            for timeframe_data in symbol_data.values():
                all_timestamps.update(timeframe_data['timestamp'])
        
        timestamps = sorted(all_timestamps)
        
        logger.info(f"🔄 Simulando {len(timestamps)} períodos")
        
        for i, current_time in enumerate(timestamps):
            if i % 1000 == 0:
                progress = (i / len(timestamps)) * 100
                logger.info(f"📊 Progresso: {progress:.1f}% ({i}/{len(timestamps)})")
            
            # Atualizar preços atuais das posições
            await self._update_positions(current_time, all_data)
            
            # Verificar stop loss e take profit
            await self._check_exit_conditions(current_time, all_data)
            
            # Gerar sinais para cada símbolo
            for symbol in self.config.symbols:
                if symbol not in all_data:
                    continue
                
                # Usar dados do timeframe principal (primeiro da lista)
                main_timeframe = self.config.timeframes[0]
                if main_timeframe not in all_data[symbol]:
                    continue
                
                symbol_data = all_data[symbol][main_timeframe]
                
                # Filtrar dados até o momento atual
                current_data = symbol_data[symbol_data['timestamp'] <= current_time]
                
                if len(current_data) < 50:  # Dados insuficientes
                    continue
                
                # Gerar sinal
                signal = await self.strategy_engine.generate_signal(symbol, symbol_data, current_time)
                
                # Executar trade se necessário
                await self._execute_signal(symbol, signal, current_time, current_data)
            
            # Registrar equity curve
            self._record_equity_point(current_time)
    
    async def _update_positions(self, current_time: datetime, all_data: Dict[str, Dict[str, pd.DataFrame]]):
        """Atualiza preços atuais das posições"""
        for symbol, position in self.positions.items():
            if symbol in all_data and self.config.timeframes[0] in all_data[symbol]:
                symbol_data = all_data[symbol][self.config.timeframes[0]]
                current_data = symbol_data[symbol_data['timestamp'] <= current_time]
                
                if not current_data.empty:
                    current_price = current_data.iloc[-1]['close']
                    position.current_price = current_price
                    
                    # Calcular PnL não realizado
                    if position.side == 'long':
                        position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
                    else:
                        position.unrealized_pnl = (position.entry_price - current_price) * position.quantity
    
    async def _check_exit_conditions(self, current_time: datetime, all_data: Dict[str, Dict[str, pd.DataFrame]]):
        """Verifica condições de saída (stop loss, take profit)"""
        positions_to_close = []
        
        for symbol, position in self.positions.items():
            if position.current_price == 0:
                continue
            
            should_exit = False
            exit_reason = ""
            
            # Stop Loss
            if position.stop_loss_price:
                if position.side == 'long' and position.current_price <= position.stop_loss_price:
                    should_exit = True
                    exit_reason = "stop_loss"
                elif position.side == 'short' and position.current_price >= position.stop_loss_price:
                    should_exit = True
                    exit_reason = "stop_loss"
            
            # Take Profit
            if position.take_profit_price and not should_exit:
                if position.side == 'long' and position.current_price >= position.take_profit_price:
                    should_exit = True
                    exit_reason = "take_profit"
                elif position.side == 'short' and position.current_price <= position.take_profit_price:
                    should_exit = True
                    exit_reason = "take_profit"
            
            if should_exit:
                positions_to_close.append((symbol, exit_reason))
        
        # Fechar posições
        for symbol, exit_reason in positions_to_close:
            await self._close_position(symbol, current_time, exit_reason)
    
    async def _execute_signal(self, symbol: str, signal: Dict[str, Any], 
                            current_time: datetime, current_data: pd.DataFrame):
        """Executa sinal de trading"""
        action = signal.get('action', 'hold')
        confidence = signal.get('confidence', 0.0)
        
        if action == 'hold' or confidence < 0.3:
            return
        
        current_price = current_data.iloc[-1]['close']
        
        # Verificar se já tem posição no símbolo
        has_position = symbol in self.positions
        
        if action == 'buy' and not has_position:
            await self._open_position(symbol, 'long', current_price, current_time, signal)
        elif action == 'sell' and not has_position:
            await self._open_position(symbol, 'short', current_price, current_time, signal)
        elif action == 'sell' and has_position and self.positions[symbol].side == 'long':
            await self._close_position(symbol, current_time, "signal_exit")
        elif action == 'buy' and has_position and self.positions[symbol].side == 'short':
            await self._close_position(symbol, current_time, "signal_exit")
    
    async def _open_position(self, symbol: str, side: str, price: float, 
                           timestamp: datetime, signal: Dict[str, Any]):
        """Abre nova posição"""
        # Calcular tamanho da posição
        max_position_value = self.current_capital * self.config.max_position_size
        quantity = max_position_value / price
        
        # Aplicar slippage
        if side == 'long':
            execution_price = price * (1 + self.config.slippage)
        else:
            execution_price = price * (1 - self.config.slippage)
        
        # Calcular comissão
        commission = max_position_value * self.config.commission
        
        # Criar posição
        position = Position(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=execution_price,
            entry_time=timestamp,
            current_price=execution_price
        )
        
        # Definir stop loss e take profit
        if side == 'long':
            position.stop_loss_price = execution_price * (1 - self.config.stop_loss)
            position.take_profit_price = execution_price * (1 + self.config.take_profit)
        else:
            position.stop_loss_price = execution_price * (1 + self.config.stop_loss)
            position.take_profit_price = execution_price * (1 - self.config.take_profit)
        
        # Atualizar capital
        self.current_capital -= commission
        
        # Armazenar posição
        self.positions[symbol] = position
        
        # Criar trade de entrada
        trade = Trade(
            timestamp=timestamp,
            symbol=symbol,
            side='buy' if side == 'long' else 'sell',
            quantity=quantity,
            price=execution_price,
            commission=commission,
            slippage=self.config.slippage,
            ai_confidence=signal.get('scores', {}).get('ai', 0.0),
            quantum_score=signal.get('scores', {}).get('quantum', 0.0),
            technical_score=signal.get('scores', {}).get('technical', 0.0),
            news_sentiment=signal.get('scores', {}).get('news', 0.0),
            risk_score=signal.get('scores', {}).get('risk', 0.0)
        )
        
        self.trades.append(trade)
        
        if self.config.detailed_logs:
            logger.info(f"📈 Posição aberta: {symbol} {side} {quantity:.6f} @ {execution_price:.2f}")
    
    async def _close_position(self, symbol: str, timestamp: datetime, exit_reason: str):
        """Fecha posição existente"""
        if symbol not in self.positions:
            return
        
        position = self.positions[symbol]
        execution_price = position.current_price
        
        # Aplicar slippage
        if position.side == 'long':
            execution_price *= (1 - self.config.slippage)
        else:
            execution_price *= (1 + self.config.slippage)
        
        # Calcular PnL
        if position.side == 'long':
            pnl = (execution_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - execution_price) * position.quantity
        
        # Calcular comissão
        position_value = execution_price * position.quantity
        commission = position_value * self.config.commission
        
        # PnL líquido
        net_pnl = pnl - commission
        pnl_percentage = (net_pnl / (position.entry_price * position.quantity)) * 100
        
        # Atualizar capital
        self.current_capital += position_value + net_pnl
        
        # Criar trade de saída
        trade = Trade(
            timestamp=timestamp,
            symbol=symbol,
            side='sell' if position.side == 'long' else 'buy',
            quantity=position.quantity,
            price=execution_price,
            commission=commission,
            slippage=self.config.slippage,
            pnl=net_pnl,
            pnl_percentage=pnl_percentage,
            duration=timestamp - position.entry_time,
            exit_reason=exit_reason
        )
        
        self.trades.append(trade)
        
        # Remover posição
        del self.positions[symbol]
        
        if self.config.detailed_logs:
            logger.info(f"📉 Posição fechada: {symbol} PnL: {net_pnl:.2f} ({pnl_percentage:.2f}%)")
    
    def _record_equity_point(self, timestamp: datetime):
        """Registra ponto na curva de equity"""
        # Calcular valor total (capital + posições não realizadas)
        total_value = self.current_capital
        
        for position in self.positions.values():
            total_value += position.unrealized_pnl
        
        # Atualizar peak e drawdown
        if total_value > self.peak_capital:
            self.peak_capital = total_value
        
        current_drawdown = (self.peak_capital - total_value) / self.peak_capital
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
        
        # Registrar ponto
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': total_value,
            'drawdown': current_drawdown,
            'cash': self.current_capital,
            'unrealized_pnl': sum(p.unrealized_pnl for p in self.positions.values())
        })
    
    def _calculate_metrics(self) -> BacktestResults:
        """Calcula métricas do backtesting"""
        results = BacktestResults(config=self.config)
        
        # Métricas básicas
        results.initial_capital = self.config.initial_capital
        results.final_capital = self.current_capital
        results.total_return = self.current_capital - self.config.initial_capital
        results.total_return_percentage = (results.total_return / self.config.initial_capital) * 100
        
        # Análise de trades
        completed_trades = [t for t in self.trades if t.pnl != 0.0]
        results.total_trades = len(completed_trades)
        
        if completed_trades:
            winning_trades = [t for t in completed_trades if t.pnl > 0]
            losing_trades = [t for t in completed_trades if t.pnl < 0]
            
            results.winning_trades = len(winning_trades)
            results.losing_trades = len(losing_trades)
            results.win_rate = (results.winning_trades / results.total_trades) * 100
            
            # Métricas de performance
            trade_returns = [t.pnl for t in completed_trades]
            results.average_trade_return = np.mean(trade_returns)
            results.largest_winning_trade = max(trade_returns) if trade_returns else 0.0
            results.largest_losing_trade = min(trade_returns) if trade_returns else 0.0
            
            if winning_trades:
                results.average_winning_trade = np.mean([t.pnl for t in winning_trades])
            
            if losing_trades:
                results.average_losing_trade = np.mean([t.pnl for t in losing_trades])
        
        # Curva de equity
        if self.equity_curve:
            equity_df = pd.DataFrame(self.equity_curve)
            equity_df.set_index('timestamp', inplace=True)
            results.equity_curve = equity_df
            
            # Retornos diários
            daily_returns = equity_df['equity'].pct_change().dropna()
            results.daily_returns = daily_returns
            
            # Métricas de risco
            if len(daily_returns) > 1:
                results.sharpe_ratio = emp.sharpe_ratio(daily_returns)
                results.sortino_ratio = emp.sortino_ratio(daily_returns)
                results.calmar_ratio = emp.calmar_ratio(daily_returns)
                results.max_drawdown = emp.max_drawdown(daily_returns)
                results.max_drawdown_percentage = results.max_drawdown * 100
                
                # VaR e CVaR
                results.value_at_risk_95 = np.percentile(daily_returns, 5)
                results.conditional_var_95 = daily_returns[daily_returns <= results.value_at_risk_95].mean()
        
        # Análise por símbolo
        for symbol in self.config.symbols:
            symbol_trades = [t for t in completed_trades if t.symbol == symbol]
            if symbol_trades:
                symbol_pnl = sum(t.pnl for t in symbol_trades)
                symbol_trades_count = len(symbol_trades)
                symbol_win_rate = len([t for t in symbol_trades if t.pnl > 0]) / symbol_trades_count * 100
                
                results.symbol_performance[symbol] = {
                    'total_pnl': symbol_pnl,
                    'trades_count': symbol_trades_count,
                    'win_rate': symbol_win_rate,
                    'avg_pnl': symbol_pnl / symbol_trades_count
                }
        
        # Análise temporal
        if not results.equity_curve.empty:
            # Retornos mensais
            monthly_equity = results.equity_curve['equity'].resample('M').last()
            results.monthly_returns = monthly_equity.pct_change().dropna()
            
            # Retornos anuais
            yearly_equity = results.equity_curve['equity'].resample('Y').last()
            results.yearly_returns = yearly_equity.pct_change().dropna()
        
        # Sequências de vitórias/derrotas
        if completed_trades:
            consecutive_wins = 0
            consecutive_losses = 0
            max_consecutive_wins = 0
            max_consecutive_losses = 0
            
            for trade in completed_trades:
                if trade.pnl > 0:
                    consecutive_wins += 1
                    consecutive_losses = 0
                    max_consecutive_wins = max(max_consecutive_wins, consecutive_wins)
                else:
                    consecutive_losses += 1
                    consecutive_wins = 0
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            
            results.maximum_consecutive_wins = max_consecutive_wins
            results.maximum_consecutive_losses = max_consecutive_losses
        
        results.trades = self.trades
        
        return results
    
    async def _save_results(self, results: BacktestResults):
        """Salva resultados do backtesting"""
        try:
            # Criar diretório de resultados
            results_dir = Path("backtest_results")
            results_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Salvar resumo em JSON
            summary = {
                'config': asdict(results.config),
                'summary': {
                    'total_trades': results.total_trades,
                    'win_rate': results.win_rate,
                    'total_return_percentage': results.total_return_percentage,
                    'sharpe_ratio': results.sharpe_ratio,
                    'max_drawdown_percentage': results.max_drawdown_percentage,
                    'execution_time': results.execution_time
                },
                'symbol_performance': results.symbol_performance
            }
            
            with open(results_dir / f"backtest_summary_{timestamp}.json", 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            # Salvar trades detalhados
            if results.trades:
                trades_df = pd.DataFrame([asdict(trade) for trade in results.trades])
                trades_df.to_csv(results_dir / f"backtest_trades_{timestamp}.csv", index=False)
            
            # Salvar curva de equity
            if not results.equity_curve.empty:
                results.equity_curve.to_csv(results_dir / f"backtest_equity_{timestamp}.csv")
            
            logger.info(f"💾 Resultados salvos em {results_dir}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar resultados: {e}")
    
    async def _generate_plots(self, results: BacktestResults):
        """Gera gráficos dos resultados"""
        try:
            # Criar diretório de gráficos
            plots_dir = Path("backtest_plots")
            plots_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Configurar estilo
            plt.style.use('seaborn-v0_8')
            sns.set_palette("husl")
            
            # 1. Curva de Equity
            if not results.equity_curve.empty:
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
                
                # Equity curve
                ax1.plot(results.equity_curve.index, results.equity_curve['equity'], 
                        linewidth=2, label='Equity')
                ax1.axhline(y=results.initial_capital, color='red', linestyle='--', 
                           alpha=0.7, label='Capital Inicial')
                ax1.set_title('Curva de Equity', fontsize=16, fontweight='bold')
                ax1.set_ylabel('Valor do Portfolio ($)')
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                
                # Drawdown
                ax2.fill_between(results.equity_curve.index, 
                               results.equity_curve['drawdown'] * 100, 0,
                               alpha=0.7, color='red', label='Drawdown')
                ax2.set_title('Drawdown', fontsize=16, fontweight='bold')
                ax2.set_ylabel('Drawdown (%)')
                ax2.set_xlabel('Data')
                ax2.legend()
                ax2.grid(True, alpha=0.3)
                
                plt.tight_layout()
                plt.savefig(plots_dir / f"equity_curve_{timestamp}.png", dpi=300, bbox_inches='tight')
                plt.close()
            
            # 2. Distribuição de Retornos
            if len(results.daily_returns) > 1:
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
                
                # Histograma
                ax1.hist(results.daily_returns * 100, bins=50, alpha=0.7, edgecolor='black')
                ax1.axvline(results.daily_returns.mean() * 100, color='red', linestyle='--', 
                           label=f'Média: {results.daily_returns.mean()*100:.2f}%')
                ax1.set_title('Distribuição de Retornos Diários', fontsize=14, fontweight='bold')
                ax1.set_xlabel('Retorno (%)')
                ax1.set_ylabel('Frequência')
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                
                # Q-Q plot
                stats.probplot(results.daily_returns, dist="norm", plot=ax2)
                ax2.set_title('Q-Q Plot (Normalidade)', fontsize=14, fontweight='bold')
                ax2.grid(True, alpha=0.3)
                
                plt.tight_layout()
                plt.savefig(plots_dir / f"returns_distribution_{timestamp}.png", dpi=300, bbox_inches='tight')
                plt.close()
            
            # 3. Performance por Símbolo
            if results.symbol_performance:
                symbols = list(results.symbol_performance.keys())
                pnls = [results.symbol_performance[s]['total_pnl'] for s in symbols]
                win_rates = [results.symbol_performance[s]['win_rate'] for s in symbols]
                
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
                
                # PnL por símbolo
                bars1 = ax1.bar(symbols, pnls, alpha=0.7)
                ax1.set_title('PnL por Símbolo', fontsize=14, fontweight='bold')
                ax1.set_ylabel('PnL ($)')
                ax1.grid(True, alpha=0.3)
                
                # Colorir barras
                for bar, pnl in zip(bars1, pnls):
                    bar.set_color('green' if pnl > 0 else 'red')
                
                # Win rate por símbolo
                bars2 = ax2.bar(symbols, win_rates, alpha=0.7, color='blue')
                ax2.set_title('Taxa de Acerto por Símbolo', fontsize=14, fontweight='bold')
                ax2.set_ylabel('Win Rate (%)')
                ax2.set_ylim(0, 100)
                ax2.grid(True, alpha=0.3)
                
                plt.tight_layout()
                plt.savefig(plots_dir / f"symbol_performance_{timestamp}.png", dpi=300, bbox_inches='tight')
                plt.close()
            
            # 4. Análise de Trades
            if results.trades:
                completed_trades = [t for t in results.trades if t.pnl != 0.0]
                
                if completed_trades:
                    trade_pnls = [t.pnl for t in completed_trades]
                    trade_durations = [t.duration.total_seconds() / 3600 for t in completed_trades if t.duration]
                    
                    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
                    
                    # PnL por trade
                    colors = ['green' if pnl > 0 else 'red' for pnl in trade_pnls]
                    ax1.bar(range(len(trade_pnls)), trade_pnls, color=colors, alpha=0.7)
                    ax1.axhline(y=0, color='black', linestyle='-', alpha=0.5)
                    ax1.set_title('PnL por Trade', fontsize=14, fontweight='bold')
                    ax1.set_xlabel('Trade #')
                    ax1.set_ylabel('PnL ($)')
                    ax1.grid(True, alpha=0.3)
                    
                    # Duração dos trades
                    if trade_durations:
                        ax2.hist(trade_durations, bins=30, alpha=0.7, edgecolor='black')
                        ax2.set_title('Distribuição de Duração dos Trades', fontsize=14, fontweight='bold')
                        ax2.set_xlabel('Duração (horas)')
                        ax2.set_ylabel('Frequência')
                        ax2.grid(True, alpha=0.3)
                    
                    plt.tight_layout()
                    plt.savefig(plots_dir / f"trade_analysis_{timestamp}.png", dpi=300, bbox_inches='tight')
                    plt.close()
            
            # 5. Gráfico Interativo com Plotly
            if not results.equity_curve.empty:
                fig = make_subplots(
                    rows=3, cols=1,
                    subplot_titles=('Curva de Equity', 'Drawdown', 'Retornos Diários'),
                    vertical_spacing=0.08,
                    row_heights=[0.5, 0.25, 0.25]
                )
                
                # Equity curve
                fig.add_trace(
                    go.Scatter(
                        x=results.equity_curve.index,
                        y=results.equity_curve['equity'],
                        mode='lines',
                        name='Equity',
                        line=dict(color='blue', width=2)
                    ),
                    row=1, col=1
                )
                
                # Linha do capital inicial
                fig.add_hline(
                    y=results.initial_capital,
                    line_dash="dash",
                    line_color="red",
                    annotation_text="Capital Inicial",
                    row=1, col=1
                )
                
                # Drawdown
                fig.add_trace(
                    go.Scatter(
                        x=results.equity_curve.index,
                        y=results.equity_curve['drawdown'] * 100,
                        mode='lines',
                        name='Drawdown',
                        fill='tonexty',
                        line=dict(color='red', width=1)
                    ),
                    row=2, col=1
                )
                
                # Retornos diários
                if len(results.daily_returns) > 1:
                    fig.add_trace(
                        go.Scatter(
                            x=results.daily_returns.index,
                            y=results.daily_returns * 100,
                            mode='lines',
                            name='Retornos Diários',
                            line=dict(color='green', width=1)
                        ),
                        row=3, col=1
                    )
                
                fig.update_layout(
                    title=f'Análise de Backtesting - {timestamp}',
                    height=800,
                    showlegend=True
                )
                
                fig.update_yaxes(title_text="Valor ($)", row=1, col=1)
                fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)
                fig.update_yaxes(title_text="Retorno (%)", row=3, col=1)
                fig.update_xaxes(title_text="Data", row=3, col=1)
                
                fig.write_html(plots_dir / f"interactive_analysis_{timestamp}.html")
            
            logger.info(f"📊 Gráficos salvos em {plots_dir}")
            
        except Exception as e:
            logger.error(f"Erro ao gerar gráficos: {e}")

# Funções de conveniência

async def run_simple_backtest(symbols: List[str], start_date: str, end_date: str,
                             initial_capital: float = 100000.0) -> BacktestResults:
    """Executa um backtesting simples"""
    config = BacktestConfig(
        start_date=datetime.strptime(start_date, '%Y-%m-%d'),
        end_date=datetime.strptime(end_date, '%Y-%m-%d'),
        symbols=symbols,
        initial_capital=initial_capital
    )
    
    engine = BacktestEngine(config)
    return await engine.run_backtest()

async def run_advanced_backtest(config_dict: Dict[str, Any]) -> BacktestResults:
    """Executa um backtesting avançado com configuração customizada"""
    config = BacktestConfig(**config_dict)
    engine = BacktestEngine(config)
    return await engine.run_backtest()

def compare_strategies(results_list: List[BacktestResults]) -> pd.DataFrame:
    """Compara múltiplas estratégias"""
    comparison_data = []
    
    for i, results in enumerate(results_list):
        comparison_data.append({
            'Strategy': f'Strategy_{i+1}',
            'Total_Return_%': results.total_return_percentage,
            'Sharpe_Ratio': results.sharpe_ratio,
            'Max_Drawdown_%': results.max_drawdown_percentage,
            'Win_Rate_%': results.win_rate,
            'Total_Trades': results.total_trades,
            'Avg_Trade_Return': results.average_trade_return,
            'Execution_Time_s': results.execution_time
        })
    
    return pd.DataFrame(comparison_data)

if __name__ == "__main__":
    # Exemplo de uso
    async def main():
        # Configuração de exemplo
        config = BacktestConfig(
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            symbols=['BTCUSDT', 'ETHUSDT'],
            initial_capital=100000.0,
            timeframes=['1h', '4h'],
            generate_plots=True,
            save_results=True
        )
        
        # Executar backtesting
        engine = BacktestEngine(config)
        results = await engine.run_backtest()
        
        # Exibir resultados
        print(f"Retorno Total: {results.total_return_percentage:.2f}%")
        print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
        print(f"Max Drawdown: {results.max_drawdown_percentage:.2f}%")
        print(f"Win Rate: {results.win_rate:.2f}%")
        print(f"Total de Trades: {results.total_trades}")
    
    # Executar exemplo
    # asyncio.run(main())

