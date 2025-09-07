import pytest
import pandas as pd
import numpy as np
from ai_model_fixed import AdvancedAIModel

@pytest.fixture
def sample_data():
    # Gerar dados de exemplo para teste
    data = {
        'open': np.random.rand(100) * 100,
        'high': np.random.rand(100) * 100 + 1,
        'low': np.random.rand(100) * 100 - 1,
        'close': np.random.rand(100) * 100,
        'volume': np.random.rand(100) * 1000
    }
    df = pd.DataFrame(data)
    df.index = pd.to_datetime(pd.date_range(start='2023-01-01', periods=100, freq='H'))
    return df

@pytest.fixture
def ai_model():
    # Configurar um modelo de IA para teste
    input_shape = (50, 5) # sequence_length, num_features
    model = AdvancedAIModel(input_shape=input_shape)
    return model

def test_prepare_data(ai_model, sample_data):
    X, y = ai_model.prepare_data(sample_data)
    assert X.shape[0] > 0
    assert X.shape[1] == ai_model.input_shape[0]
    assert X.shape[2] == ai_model.input_shape[1]
    assert 'buy_signal' in y
    assert 'sell_signal' in y

def test_train_model(ai_model, sample_data):
    X, y = ai_model.prepare_data(sample_data)
    if X.shape[0] == 0:
        pytest.skip("Dados insuficientes para treinamento.")
    
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train = {k: v[:split_idx] for k, v in y.items()}
    y_val = {k: v[split_idx:] for k, v in y.items()}

    history = ai_model.train(X_train, y_train, X_val, y_val, epochs=1, batch_size=1)
    assert 'loss' in history.history
    assert ai_model.is_trained

def test_predict_model(ai_model, sample_data):
    X, y = ai_model.prepare_data(sample_data)
    if X.shape[0] == 0:
        pytest.skip("Dados insuficientes para predição.")
    
    # Treinar o modelo primeiro para que is_trained seja True
    split_idx = int(len(X) * 0.8)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train = {k: v[:split_idx] for k, v in y.items()}
    y_val = {k: v[split_idx:] for k, v in y.items()}
    ai_model.train(X_train, y_train, X_val, y_val, epochs=1, batch_size=1)

    predictions = ai_model.predict(X[:1])
    assert predictions is not None
    assert 'buy_signal' in predictions
    assert 'sell_signal' in predictions

def test_generate_advanced_signal(ai_model):
    predictions = {'buy_signal': np.array([0.8]), 'sell_signal': np.array([0.2])}
    signal = ai_model.generate_advanced_signal(predictions)
    assert signal['action'] == 'buy'
    assert signal['confidence'] == 0.8

    predictions = {'buy_signal': np.array([0.1]), 'sell_signal': np.array([0.9])}
    signal = ai_model.generate_advanced_signal(predictions)
    assert signal['action'] == 'sell'
    assert signal['confidence'] == 0.9

    predictions = {'buy_signal': np.array([0.4]), 'sell_signal': np.array([0.45])}
    signal = ai_model.generate_advanced_signal(predictions)
    assert signal['action'] == 'hold'
    assert signal['confidence'] == 0.45



