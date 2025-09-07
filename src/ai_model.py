import tensorflow as tf
from tensorflow.keras.models import Model
from tensorflow.keras.layers import (
    Input, LSTM, Dense, Dropout, BatchNormalization, 
    Attention, MultiHeadAttention, LayerNormalization,
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
from typing import Tuple, Dict, List, Optional
from config import config
from utils import setup_logging

logger = setup_logging(__name__)

class AdvancedAIModel:
    """
    Modelo de IA avançado para trading com arquitetura híbrida:
    - Transformer com Multi-Head Attention
    - LSTM bidirecional
    - CNN para extração de padrões locais
    - Ensemble de múltiplos modelos
    """
    
    def __init__(self, input_shape: Tuple[int, int], model_name: str = "advanced_trader"):
        self.input_shape = input_shape
        self.model_name = model_name
        self.model = None
        self.scaler = RobustScaler()  # Mais robusto que MinMaxScaler
        self.is_trained = False
        self.training_history = None
        self.feature_importance = None
        
        # Configurações do modelo
        self.config = config.ai
        
        # Métricas de performance
        self.metrics = {
            'train_loss': [],
            'val_loss': [],
            'train_mae': [],
            'val_mae': [],
            'r2_score': 0.0,
            'sharpe_ratio': 0.0
        }
        
        self._build_model()
    
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
        price_prediction = Dense(1, activation='linear', name='price_prediction')(x)
        direction_prediction = Dense(3, activation='softmax', name='direction_prediction')(x)  # buy/sell/hold
        volatility_prediction = Dense(1, activation='sigmoid', name='volatility_prediction')(x)
        
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
                'direction': 2.0,  # Maior peso para direção
                'volatility': 0.5
            },
            metrics={
                'price_prediction': ['mae'],
                'direction_prediction': ['accuracy'],
                'volatility_prediction': ['binary_accuracy']
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
        
        # Engenharia de features
        df = self._engineer_features(market_data.copy())
        
        # Criar sequências
        X, y = self._create_sequences(df)
        
        # Normalizar features
        if X.size == 0:
            return X, y
        X_scaled = self._scale_features(X)
        return X_scaled, y
    
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Engenharia de features avançada"""
        # Features técnicas básicas
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        df['volatility'] = df['returns'].rolling(20).std()
        
        # Médias móveis
        for period in [5, 10, 20, 50]:
            df[f'sma_{period}'] = df['close'].rolling(period).mean()
            df[f'ema_{period}'] = df['close'].ewm(span=period).mean()
        
        # Indicadores técnicos
        df['rsi'] = self._calculate_rsi(df['close'])
        df['macd'], df['macd_signal'] = self._calculate_macd(df['close'])
        df['bb_upper'], df['bb_lower'] = self._calculate_bollinger_bands(df['close'])
        
        # Features de volume
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # Features de momentum
        df['momentum_5'] = df['close'] / df['close'].shift(5) - 1
        df['momentum_10'] = df['close'] / df['close'].shift(10) - 1
        
        # Features de volatilidade
        df['volatility_ratio'] = df['volatility'] / df['volatility'].rolling(50).mean()
        
        # Remover NaN
        df = df.dropna()
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calcula RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_macd(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series]:
        """Calcula MACD"""
        ema12 = prices.ewm(span=12).mean()
        ema26 = prices.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        return macd, signal
    
    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series]:
        """Calcula Bandas de Bollinger"""
        sma = prices.rolling(period).mean()
        std = prices.rolling(period).std()
        upper = sma + (std * 2)
        lower = sma - (std * 2)
        return upper, lower
    
    def _create_sequences(self, df: pd.DataFrame) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """Cria sequências para o modelo"""
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
            # Features de entrada
            X.append(df[feature_cols].iloc[i-self.config.sequence_length:i].values)
            
            # Target: preço futuro
            current_price = df['close'].iloc[i-1]
            future_price = df['close'].iloc[i]
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
        
        return np.array(X), {
            'price': np.array(y_price),
            'direction': np.array(y_direction),
            'volatility': np.array(y_volatility)
        }
    
    def _scale_features(self, X: np.ndarray) -> np.ndarray:
        """Normaliza features usando RobustScaler"""
        # Reshape para 2D
        original_shape = X.shape
        X_reshaped = X.reshape(-1, X.shape[-1])
        
        # Fit e transform
        X_scaled = self.scaler.fit_transform(X_reshaped)
        
        # Reshape de volta
        return X_scaled.reshape(original_shape)
    
    def train(self, X_train: np.ndarray, y_train: Dict[str, np.ndarray], 
              X_val: Optional[np.ndarray] = None, y_val: Optional[Dict[str, np.ndarray]] = None) -> Dict:
        """
        Treina o modelo com dados preparados
        """
        logger.info("Iniciando treinamento do modelo avançado...")
        
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
                f'models/{self.model_name}_best.h5',
                monitor='val_loss',
                save_best_only=True,
                verbose=1
            )
        ]
        
        # Criar diretório de modelos
        os.makedirs('models', exist_ok=True)
        
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
        self._calculate_metrics(X_val, y_val)
        
        logger.info("Treinamento concluído!")
        return history.history
    
    def _calculate_metrics(self, X_val: np.ndarray, y_val: Dict[str, np.ndarray]):
        """Calcula métricas de performance"""
        if X_val is None:
            return
        
        predictions = self.model.predict(X_val)
        
        # R² Score para previsão de preço
        self.metrics['r2_score'] = r2_score(y_val['price'], predictions['price'])
        
        # Sharpe Ratio simulado
        returns = predictions['price'].flatten()
        if np.std(returns) > 0:
            self.metrics['sharpe_ratio'] = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        logger.info(f"R² Score: {self.metrics['r2_score']:.4f}")
        logger.info(f"Sharpe Ratio: {self.metrics['sharpe_ratio']:.4f}")
    
    def predict(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        """Faz previsões com o modelo treinado"""
        if not self.is_trained:
            raise ValueError("Modelo não foi treinado ainda!")
        
        # Normalizar dados
        X_scaled = self.scaler.transform(X.reshape(-1, X.shape[-1])).reshape(X.shape)
        
        # Previsão
        predictions = self.model.predict(X_scaled)
        
        return predictions
    
    def generate_advanced_signal(self, predictions: Dict[str, np.ndarray], 
                                confidence_threshold: float = 0.7) -> Dict:
        """
        Gera sinal de trading avançado baseado em múltiplas previsões
        """
        price_change = predictions['price'][0][0]
        direction_probs = predictions['direction'][0]
        volatility_prob = predictions['volatility'][0][0]
        
        # Determinar direção com maior probabilidade
        direction_idx = np.argmax(direction_probs)
        direction_confidence = direction_probs[direction_idx]
        
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
        
        return {
            'action': action,
            'confidence': float(direction_confidence),
            'price_change_prediction': float(price_change),
            'volatility_prediction': float(volatility_prob),
            'direction_probabilities': {
                'buy': float(direction_probs[0]),
                'hold': float(direction_probs[1]),
                'sell': float(direction_probs[2])
            }
        }
    
    def save_model(self, filepath: str = None):
        """Salva o modelo e scaler"""
        if filepath is None:
            filepath = f'models/{self.model_name}'
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Salvar modelo
        self.model.save(f'{filepath}_model.h5')
        
        # Salvar scaler
        joblib.dump(self.scaler, f'{filepath}_scaler.pkl')
        
        # Salvar métricas
        joblib.dump(self.metrics, f'{filepath}_metrics.pkl')
        
        logger.info(f"Modelo salvo em {filepath}")
    
    def load_model(self, filepath: str):
        """Carrega modelo e scaler salvos"""
        # Carregar modelo
        self.model = tf.keras.models.load_model(f'{filepath}_model.h5')
        
        # Carregar scaler
        self.scaler = joblib.load(f'{filepath}_scaler.pkl')
        
        # Carregar métricas
        self.metrics = joblib.load(f'{filepath}_metrics.pkl')
        
        self.is_trained = True
        logger.info(f"Modelo carregado de {filepath}")

if __name__ == "__main__":
    # Teste do modelo avançado
    logger.info("Testando modelo de IA avançado...")
    
    # Simular dados de mercado
    np.random.seed(42)
    dates = pd.date_range(start='2023-01-01', periods=1000, freq='1H')
    
    # Simular preços com tendência e volatilidade
    returns = np.random.normal(0.0001, 0.02, 1000)
    prices = 50000 * np.exp(np.cumsum(returns))
    
    market_data = pd.DataFrame({
        'timestamp': dates,
        'open': prices * (1 + np.random.normal(0, 0.001, 1000)),
        'high': prices * (1 + np.random.uniform(0, 0.02, 1000)),
        'low': prices * (1 - np.random.uniform(0, 0.02, 1000)),
        'close': prices,
        'volume': np.random.lognormal(10, 1, 1000)
    })
    
    # Criar e treinar modelo
    model = AdvancedAIModel(input_shape=(60, 15))  # 60 períodos, ~15 features
    
    # Preparar dados
    X, y = model.prepare_data(market_data)
    
    # Dividir em treino e validação
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train = {k: v[:split_idx] for k, v in y.items()}
    y_val = {k: v[split_idx:] for k, v in y.items()}
    
    # Treinar modelo
    history = model.train(X_train, y_train, X_val, y_val)
    
    # Fazer previsão
    test_sample = X_val[:1]
    predictions = model.predict(test_sample)
    signal = model.generate_advanced_signal(predictions)
    
    logger.info(f"Sinal gerado: {signal}")
    
    # Salvar modelo
    model.save_model()
    
    logger.info("Teste concluído!")



    def save_model(self, path: str = None):
        """
        Salva o modelo treinado e o scaler.
        """
        if not self.is_trained:
            logger.warning("Modelo não treinado, não pode ser salvo.")
            return
        
        if path is None:
            path = f"models/{self.model_name}_final.h5"
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.model.save(path)
        joblib.dump(self.scaler, f"models/{self.model_name}_scaler.pkl")
        logger.info(f"Modelo e scaler salvos em {path} e models/{self.model_name}_scaler.pkl")

    def load_model(self, path: str = None):
        """
        Carrega um modelo treinado e o scaler.
        """
        if path is None:
            path = f"models/{self.model_name}_final.h5"
        
        if not os.path.exists(path):
            logger.warning(f"Modelo não encontrado em {path}. Treine um novo modelo ou verifique o caminho.")
            return

        try:
            self.model = tf.keras.models.load_model(path)
            self.scaler = joblib.load(f"models/{self.model_name}_scaler.pkl")
            self.is_trained = True
            logger.info(f"Modelo e scaler carregados de {path} e models/{self.model_name}_scaler.pkl")
        except Exception as e:
            logger.error(f"Erro ao carregar o modelo de {path}: {e}")
            self.model = None
            self.scaler = RobustScaler() # Reset scaler
            self.is_trained = False



