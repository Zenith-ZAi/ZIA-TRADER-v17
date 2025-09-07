"""
Modelo de IA Avançado Corrigido para RoboTrader
Versão: 3.0 - Correção Crítica do Carregamento

Correções implementadas:
- Carregamento correto do modelo TensorFlow
- Verificação de integridade do modelo
- Sistema de fallback robusto
- Tratamento de erros aprimorado
- Validação de dados de entrada
"""

import tensorflow as tf
from tensorflow.keras.models import Model, load_model
from tensorflow.keras.layers import (
    Input, LSTM, Dense, Dropout, BatchNormalization, 
    MultiHeadAttention, LayerNormalization,
    Conv1D, GlobalMaxPooling1D, Concatenate, Add
)
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import numpy as np
import pandas as pd
import joblib
import os
import json
from typing import Tuple, Dict, List, Optional
from datetime import datetime
from config import config
from utils import setup_logging

logger = setup_logging(__name__)

class AdvancedAIModelFixed:
    """
    Modelo de IA avançado CORRIGIDO para trading com arquitetura híbrida:
    - Transformer com Multi-Head Attention
    - LSTM bidirecional
    - CNN para extração de padrões locais
    - Sistema de carregamento robusto
    """
    
    def __init__(self, input_shape: Tuple[int, int], model_name: str = "advanced_trader_fixed"):
        self.input_shape = input_shape
        self.model_name = model_name
        self.model = None
        self.scaler = RobustScaler()
        self.is_trained = False
        self.training_history = None
        self.feature_importance = None
        self.model_path = f"models/{self.model_name}"
        
        # Configurações do modelo
        self.config = config.ai if hasattr(config, 'ai') else self._get_default_config()
        
        # Métricas de performance
        self.metrics = {
            'train_loss': [],
            'val_loss': [],
            'train_mae': [],
            'val_mae': [],
            'r2_score': 0.0,
            'sharpe_ratio': 0.0,
            'last_updated': datetime.now()
        }
        
        # Criar diretório de modelos
        os.makedirs("models", exist_ok=True)
        
        # Tentar carregar modelo existente primeiro
        if not self._load_saved_model():
            logger.info("Nenhum modelo salvo encontrado. Construindo novo modelo...")
            self._build_model()
    
    def _get_default_config(self):
        """Configuração padrão caso config.ai não exista"""
        class DefaultConfig:
            sequence_length = 60
            dropout_rate = 0.3
            learning_rate = 0.001
            lstm_units = [128, 64, 32]
            batch_size = 32
            epochs = 100
            validation_split = 0.2
        
        return DefaultConfig()
    
    def _load_saved_model(self) -> bool:
        """
        CORREÇÃO CRÍTICA: Carrega modelo salvo corretamente
        """
        try:
            model_file = f"{self.model_path}.h5"
            scaler_file = f"{self.model_path}_scaler.pkl"
            metadata_file = f"{self.model_path}_metadata.json"
            
            # Verificar se todos os arquivos existem
            if not all(os.path.exists(f) for f in [model_file, scaler_file]):
                logger.info("Arquivos do modelo não encontrados")
                return False
            
            # Carregar modelo TensorFlow
            logger.info(f"Carregando modelo de {model_file}...")
            self.model = load_model(model_file, compile=False)
            
            # Recompilar modelo com configurações corretas
            self.model.compile(
                optimizer=Adam(learning_rate=self.config.learning_rate),
                loss={
                    'price': 'mse',
                    'direction': 'categorical_crossentropy',
                    'volatility': 'binary_crossentropy'
                },
                loss_weights={
                    'price': 1.0,
                    'direction': 2.0,
                    'volatility': 0.5
                },
                metrics={
                    'price': ['mae'],
                    'direction': ['accuracy'],
                    'volatility': ['binary_accuracy']
                }
            )
            
            # Carregar scaler
            logger.info(f"Carregando scaler de {scaler_file}...")
            self.scaler = joblib.load(scaler_file)
            
            # Carregar metadata se existir
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    self.metrics.update(metadata.get('metrics', {}))
                    self.training_history = metadata.get('training_history', None)
                    logger.info(f"Metadata carregada: {metadata.get('trained_on', 'N/A')}")
            
            # Verificar integridade do modelo
            if self._validate_model():
                self.is_trained = True
                logger.info("✅ Modelo carregado e validado com sucesso!")
                return True
            else:
                logger.error("❌ Modelo carregado falhou na validação")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erro ao carregar modelo: {e}")
            self.model = None
            self.scaler = RobustScaler()
            self.is_trained = False
            return False
    
    def _validate_model(self) -> bool:
        """Valida se o modelo carregado está funcionando corretamente"""
        try:
            if self.model is None:
                return False
            
            # Criar dados de teste sintéticos
            test_input = np.random.random((1, *self.input_shape))
            
            # Tentar fazer uma predição
            predictions = self.model.predict(test_input, verbose=0)
            
            # Verificar se as saídas têm o formato esperado
            expected_outputs = ['price', 'direction', 'volatility']
            if not all(output in predictions for output in expected_outputs):
                logger.error("Modelo não possui as saídas esperadas")
                return False
            
            # Verificar dimensões das saídas
            if (predictions['price'].shape != (1, 1) or 
                predictions['direction'].shape != (1, 3) or 
                predictions['volatility'].shape != (1, 1)):
                logger.error("Dimensões das saídas do modelo incorretas")
                return False
            
            logger.info("Modelo passou na validação")
            return True
            
        except Exception as e:
            logger.error(f"Erro na validação do modelo: {e}")
            return False
    
    def _build_model(self) -> Model:
        """Constrói a arquitetura avançada do modelo"""
        logger.info("Construindo modelo de IA avançado...")
        
        # Input layer
        inputs = Input(shape=self.input_shape, name='market_data')
        
        # Branch 1: CNN para padrões locais
        cnn_branch = self._build_cnn_branch(inputs)
        
        # Branch 2: LSTM bidirecional para sequências temporais
        lstm_branch = self._build_lstm_branch(inputs)
        
        # Branch 3: Transformer com Multi-Head Attention
        transformer_branch = self._build_transformer_branch(inputs)
        
        # Combinar branches
        combined = Concatenate(name='combine_branches')([
            cnn_branch, lstm_branch, transformer_branch
        ])
        
        # Camadas finais de decisão
        x = Dense(256, activation='relu', name='decision_dense1')(combined)
        x = BatchNormalization(name='decision_bn1')(x)
        x = Dropout(self.config.dropout_rate, name='decision_dropout1')(x)
        
        x = Dense(128, activation='relu', name='decision_dense2')(x)
        x = BatchNormalization(name='decision_bn2')(x)
        x = Dropout(self.config.dropout_rate, name='decision_dropout2')(x)
        
        x = Dense(64, activation='relu', name='decision_dense3')(x)
        x = Dropout(self.config.dropout_rate / 2, name='decision_dropout3')(x)
        
        # Múltiplas saídas
        price_prediction = Dense(1, activation='linear', name='price')(x)
        direction_prediction = Dense(3, activation='softmax', name='direction')(x)
        volatility_prediction = Dense(1, activation='sigmoid', name='volatility')(x)
        
        # Criar modelo
        self.model = Model(
            inputs=inputs,
            outputs={
                'price': price_prediction,
                'direction': direction_prediction,
                'volatility': volatility_prediction
            },
            name=self.model_name
        )
        
        # Compilar modelo
        self.model.compile(
            optimizer=Adam(learning_rate=self.config.learning_rate),
            loss={
                'price': 'mse',
                'direction': 'categorical_crossentropy',
                'volatility': 'binary_crossentropy'
            },
            loss_weights={
                'price': 1.0,
                'direction': 2.0,
                'volatility': 0.5
            },
            metrics={
                'price': ['mae'],
                'direction': ['accuracy'],
                'volatility': ['binary_accuracy']
            }
        )
        
        logger.info(f"Modelo construído com {self.model.count_params():,} parâmetros")
        return self.model
    
    def _build_cnn_branch(self, inputs: Input) -> tf.Tensor:
        """Constrói branch CNN para padrões locais"""
        x = Conv1D(64, 3, activation='relu', padding='same', name='cnn_conv1')(inputs)
        x = BatchNormalization(name='cnn_bn1')(x)
        x = Dropout(0.2, name='cnn_dropout1')(x)
        
        x = Conv1D(32, 5, activation='relu', padding='same', name='cnn_conv2')(x)
        x = BatchNormalization(name='cnn_bn2')(x)
        x = Dropout(0.2, name='cnn_dropout2')(x)
        
        x = GlobalMaxPooling1D(name='cnn_pool')(x)
        return x
    
    def _build_lstm_branch(self, inputs: Input) -> tf.Tensor:
        """Constrói branch LSTM bidirecional"""
        x = tf.keras.layers.Bidirectional(
            LSTM(self.config.lstm_units[0], return_sequences=True, dropout=0.2),
            name='lstm_bi1'
        )(inputs)
        x = BatchNormalization(name='lstm_bn1')(x)
        
        x = tf.keras.layers.Bidirectional(
            LSTM(self.config.lstm_units[1], return_sequences=True, dropout=0.2),
            name='lstm_bi2'
        )(x)
        x = BatchNormalization(name='lstm_bn2')(x)
        
        x = tf.keras.layers.Bidirectional(
            LSTM(self.config.lstm_units[2], dropout=0.2),
            name='lstm_bi3'
        )(x)
        return x
    
    def _build_transformer_branch(self, inputs: Input) -> tf.Tensor:
        """Constrói branch Transformer com Multi-Head Attention"""
        # Positional encoding
        x = Dense(128, activation='relu', name='transformer_embed')(inputs)
        
        # Multi-Head Attention
        attention_output = MultiHeadAttention(
            num_heads=8,
            key_dim=64,
            name='transformer_attention'
        )(x, x)
        
        # Add & Norm
        x = Add(name='transformer_add1')([x, attention_output])
        x = LayerNormalization(name='transformer_norm1')(x)
        
        # Feed Forward
        ff_output = Dense(256, activation='relu', name='transformer_ff1')(x)
        ff_output = Dropout(0.1, name='transformer_dropout1')(ff_output)
        ff_output = Dense(128, activation='relu', name='transformer_ff2')(ff_output)
        
        # Add & Norm
        x = Add(name='transformer_add2')([x, ff_output])
        x = LayerNormalization(name='transformer_norm2')(x)
        
        # Global pooling
        x = tf.keras.layers.GlobalAveragePooling1D(name='transformer_pool')(x)
        return x
    
    def prepare_data(self, market_data: pd.DataFrame) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """
        Prepara dados para treinamento com engenharia de features avançada
        """
        logger.info("Preparando dados com engenharia de features...")
        
        if market_data.empty:
            logger.warning("DataFrame vazio fornecido")
            return np.array([]), {
                'price': np.array([]),
                'direction': np.array([]),
                'volatility': np.array([])
            }
        
        try:
            # Engenharia de features
            df = self._engineer_features(market_data.copy())
            
            # Criar sequências
            X, y = self._create_sequences(df)
            
            # Normalizar features
            if X.size == 0:
                return X, y
            
            X_scaled = self._scale_features(X)
            return X_scaled, y
            
        except Exception as e:
            logger.error(f"Erro na preparação de dados: {e}")
            return np.array([]), {
                'price': np.array([]),
                'direction': np.array([]),
                'volatility': np.array([])
            }
    
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Engenharia de features avançada com tratamento de erros"""
        try:
            # Verificar colunas necessárias
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                raise ValueError(f"Colunas ausentes: {missing_cols}")
            
            # Features técnicas básicas
            df['returns'] = df['close'].pct_change()
            df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
            df['volatility'] = df['returns'].rolling(20, min_periods=1).std()
            
            # Médias móveis
            for period in [5, 10, 20, 50]:
                df[f'sma_{period}'] = df['close'].rolling(period, min_periods=1).mean()
                df[f'ema_{period}'] = df['close'].ewm(span=period).mean()
            
            # Indicadores técnicos
            df['rsi'] = self._calculate_rsi(df['close'])
            df['macd'], df['macd_signal'] = self._calculate_macd(df['close'])
            df['bb_upper'], df['bb_lower'] = self._calculate_bollinger_bands(df['close'])
            
            # Features de volume
            df['volume_sma'] = df['volume'].rolling(20, min_periods=1).mean()
            df['volume_ratio'] = df['volume'] / df['volume_sma']
            
            # Features de momentum
            df['momentum_5'] = df['close'] / df['close'].shift(5) - 1
            df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
            
            # Features de volatilidade
            df['volatility_ratio'] = df['volatility'] / df['volatility'].rolling(50, min_periods=1).mean()
            
            # Substituir infinitos e NaN
            df = df.replace([np.inf, -np.inf], np.nan)
            df = df.fillna(method='ffill').fillna(method='bfill').fillna(0)
            
            return df
            
        except Exception as e:
            logger.error(f"Erro na engenharia de features: {e}")
            return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calcula RSI com tratamento de erros"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period, min_periods=1).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period, min_periods=1).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            return rsi.fillna(50)  # RSI neutro para valores NaN
        except:
            return pd.Series([50] * len(prices), index=prices.index)
    
    def _calculate_macd(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series]:
        """Calcula MACD com tratamento de erros"""
        try:
            ema12 = prices.ewm(span=12).mean()
            ema26 = prices.ewm(span=26).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9).mean()
            return macd.fillna(0), signal.fillna(0)
        except:
            zeros = pd.Series([0] * len(prices), index=prices.index)
            return zeros, zeros
    
    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series]:
        """Calcula Bandas de Bollinger com tratamento de erros"""
        try:
            sma = prices.rolling(period, min_periods=1).mean()
            std = prices.rolling(period, min_periods=1).std()
            upper = sma + (std * 2)
            lower = sma - (std * 2)
            return upper.fillna(prices), lower.fillna(prices)
        except:
            return prices, prices
    
    def _create_sequences(self, df: pd.DataFrame) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """Cria sequências para o modelo com validação robusta"""
        try:
            feature_cols = [col for col in df.columns if col not in ['close', 'timestamp']]
            
            if len(df) < self.config.sequence_length:
                logger.warning(f"Dados insuficientes para criar sequências. Necessário: {self.config.sequence_length}, Disponível: {len(df)}")
                return np.array([]), {
                    'price': np.array([]),
                    'direction': np.array([]),
                    'volatility': np.array([])
                }
            
            X, y_price, y_direction, y_volatility = [], [], [], []
            
            for i in range(self.config.sequence_length, len(df)):
                try:
                    # Features de entrada
                    sequence_data = df[feature_cols].iloc[i-self.config.sequence_length:i].values
                    
                    # Verificar se há dados válidos
                    if np.isnan(sequence_data).any() or np.isinf(sequence_data).any():
                        continue
                    
                    X.append(sequence_data)
                    
                    # Target: preço futuro
                    current_price = df['close'].iloc[i-1]
                    future_price = df['close'].iloc[i]
                    
                    if current_price <= 0 or future_price <= 0:
                        continue
                    
                    price_change = (future_price - current_price) / current_price
                    y_price.append(price_change)
                    
                    # Target: direção (buy=0, hold=1, sell=2)
                    if price_change > 0.01:  # 1% de alta
                        direction = [1, 0, 0]  # buy
                    elif price_change < -0.01:  # 1% de baixa
                        direction = [0, 0, 1]  # sell
                    else:
                        direction = [0, 1, 0]  # hold
                    y_direction.append(direction)
                    
                    # Target: volatilidade alta (>2%)
                    volatility_high = 1 if abs(price_change) > 0.02 else 0
                    y_volatility.append(volatility_high)
                    
                except Exception as e:
                    logger.debug(f"Erro ao processar sequência {i}: {e}")
                    continue
            
            if not X:
                logger.warning("Nenhuma sequência válida foi criada")
                return np.array([]), {
                    'price': np.array([]),
                    'direction': np.array([]),
                    'volatility': np.array([])
                }
            
            return np.array(X), {
                'price': np.array(y_price),
                'direction': np.array(y_direction),
                'volatility': np.array(y_volatility)
            }
            
        except Exception as e:
            logger.error(f"Erro ao criar sequências: {e}")
            return np.array([]), {
                'price': np.array([]),
                'direction': np.array([]),
                'volatility': np.array([])
            }
    
    def _scale_features(self, X: np.ndarray) -> np.ndarray:
        """Normaliza features usando RobustScaler com tratamento de erros"""
        try:
            # Reshape para 2D
            original_shape = X.shape
            X_reshaped = X.reshape(-1, X.shape[-1])
            
            # Verificar se há dados válidos
            if np.isnan(X_reshaped).any() or np.isinf(X_reshaped).any():
                logger.warning("Dados inválidos detectados, aplicando limpeza")
                X_reshaped = np.nan_to_num(X_reshaped, nan=0.0, posinf=1.0, neginf=-1.0)
            
            # Fit e transform
            X_scaled = self.scaler.fit_transform(X_reshaped)
            
            # Reshape de volta
            return X_scaled.reshape(original_shape)
            
        except Exception as e:
            logger.error(f"Erro na normalização: {e}")
            return X
    
    def predict(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        """Faz previsões com o modelo treinado com validação robusta"""
        if not self.is_trained or self.model is None:
            raise ValueError("Modelo não foi treinado ainda!")
        
        try:
            # Validar entrada
            if X.size == 0:
                raise ValueError("Dados de entrada vazios")
            
            if len(X.shape) != 3:
                raise ValueError(f"Formato de entrada inválido: {X.shape}")
            
            # Normalizar dados
            X_scaled = self.scaler.transform(X.reshape(-1, X.shape[-1])).reshape(X.shape)
            
            # Verificar se há dados inválidos
            if np.isnan(X_scaled).any() or np.isinf(X_scaled).any():
                logger.warning("Dados inválidos na entrada, aplicando limpeza")
                X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=1.0, neginf=-1.0)
            
            # Previsão
            predictions = self.model.predict(X_scaled, verbose=0)
            
            return predictions
            
        except Exception as e:
            logger.error(f"Erro na predição: {e}")
            # Retornar predições neutras em caso de erro
            return {
                'price': np.array([[0.0]]),
                'direction': np.array([[0.33, 0.34, 0.33]]),  # Neutro
                'volatility': np.array([[0.5]])  # Neutro
            }
    
    def generate_advanced_signal(self, predictions: Dict[str, np.ndarray], 
                                confidence_threshold: float = 0.6) -> Dict:
        """
        Gera sinal de trading avançado baseado em múltiplas previsões
        """
        try:
            price_change = float(predictions['price'][0][0])
            direction_probs = predictions['direction'][0]
            volatility_prob = float(predictions['volatility'][0][0])
            
            # Determinar direção com maior probabilidade
            direction_idx = np.argmax(direction_probs)
            direction_confidence = float(direction_probs[direction_idx])
            
            # Mapear índice para ação
            actions = ['buy', 'hold', 'sell']
            action = actions[direction_idx]
            
            # Ajustar baseado na volatilidade
            if volatility_prob > 0.7:  # Alta volatilidade
                if action != 'hold':
                    direction_confidence *= 0.8  # Reduzir confiança
            
            # Verificar threshold de confiança
            if direction_confidence < confidence_threshold:
                action = 'hold'
                direction_confidence = 0.5
            
            return {
                'action': action,
                'confidence': direction_confidence,
                'price_change_prediction': price_change,
                'volatility_prediction': volatility_prob,
                'timestamp': datetime.now().isoformat(),
                'model_version': '3.0_fixed'
            }
            
        except Exception as e:
            logger.error(f"Erro na geração de sinal: {e}")
            return {
                'action': 'hold',
                'confidence': 0.0,
                'price_change_prediction': 0.0,
                'volatility_prediction': 0.5,
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def save_model(self, path: str = None) -> bool:
        """
        Salva o modelo treinado, scaler e metadata de forma robusta
        """
        if not self.is_trained or self.model is None:
            logger.warning("Modelo não treinado, não pode ser salvo.")
            return False
        
        try:
            if path is None:
                path = self.model_path
            
            # Salvar modelo TensorFlow
            model_file = f"{path}.h5"
            self.model.save(model_file, save_format='h5')
            logger.info(f"Modelo salvo em {model_file}")
            
            # Salvar scaler
            scaler_file = f"{path}_scaler.pkl"
            joblib.dump(self.scaler, scaler_file)
            logger.info(f"Scaler salvo em {scaler_file}")
            
            # Salvar metadata
            metadata = {
                'input_shape': self.input_shape,
                'model_name': self.model_name,
                'trained_on': datetime.now().isoformat(),
                'metrics': self.metrics,
                'training_history': self.training_history,
                'version': '3.0_fixed'
            }
            
            metadata_file = f"{path}_metadata.json"
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2, default=str)
            logger.info(f"Metadata salva em {metadata_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao salvar modelo: {e}")
            return False
    
    def train(self, X_train: np.ndarray, y_train: Dict[str, np.ndarray], 
              X_val: Optional[np.ndarray] = None, y_val: Optional[Dict[str, np.ndarray]] = None) -> Dict:
        """
        Treina o modelo com dados preparados e validação robusta
        """
        logger.info("Iniciando treinamento do modelo avançado...")
        
        try:
            # Validar dados de entrada
            if X_train.size == 0 or not y_train or any(len(y) == 0 for y in y_train.values()):
                raise ValueError("Dados de treinamento vazios ou inválidos")
            
            # Callbacks
            callbacks = [
                EarlyStopping(
                    monitor='val_loss',
                    patience=15,
                    restore_best_weights=True,
                    verbose=1
                ),
                ReduceLROnPlateau(
                    monitor='val_loss',
                    factor=0.5,
                    patience=10,
                    min_lr=1e-7,
                    verbose=1
                ),
                ModelCheckpoint(
                    f'{self.model_path}_best.h5',
                    monitor='val_loss',
                    save_best_only=True,
                    verbose=1
                )
            ]
            
            # Treinamento
            history = self.model.fit(
                X_train,
                y_train,
                batch_size=self.config.batch_size,
                epochs=self.config.epochs,
                validation_data=(X_val, y_val) if X_val is not None else None,
                validation_split=self.config.validation_split if X_val is None else 0.0,
                callbacks=callbacks,
                verbose=1
            )
            
            self.training_history = history.history
            self.is_trained = True
            
            # Calcular métricas finais
            if X_val is not None and y_val is not None:
                self._calculate_metrics(X_val, y_val)
            
            # Salvar modelo automaticamente após treinamento
            self.save_model()
            
            logger.info("✅ Treinamento concluído com sucesso!")
            return history.history
            
        except Exception as e:
            logger.error(f"❌ Erro no treinamento: {e}")
            return {}
    
    def _calculate_metrics(self, X_val: np.ndarray, y_val: Dict[str, np.ndarray]):
        """Calcula métricas de performance com tratamento de erros"""
        try:
            predictions = self.model.predict(X_val, verbose=0)
            
            # R² Score para previsão de preço
            if len(y_val['price']) > 0 and len(predictions['price']) > 0:
                self.metrics['r2_score'] = r2_score(y_val['price'], predictions['price'])
            
            # Sharpe Ratio simulado
            returns = predictions['price'].flatten()
            if len(returns) > 1 and np.std(returns) > 0:
                self.metrics['sharpe_ratio'] = np.mean(returns) / np.std(returns) * np.sqrt(252)
            
            self.metrics['last_updated'] = datetime.now()
            
            logger.info(f"R² Score: {self.metrics['r2_score']:.4f}")
            logger.info(f"Sharpe Ratio: {self.metrics['sharpe_ratio']:.4f}")
            
        except Exception as e:
            logger.error(f"Erro no cálculo de métricas: {e}")

# Instância global para compatibilidade
AdvancedAIModel = AdvancedAIModelFixed

