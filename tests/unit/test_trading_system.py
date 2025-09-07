"""
Testes Unitários - Sistema de Trading RoboTrader 2.0
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from decimal import Decimal

# Imports do sistema (assumindo estrutura do projeto)
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))

from robot_trader import RobotTrader
from ai_model import AIModel
from risk_management import RiskManager
from market_data import MarketDataManager
from broker_api import BrokerAPI

class TestRobotTrader:
    """Testes para a classe principal RobotTrader"""
    
    @pytest.fixture
    def robot_trader(self):
        """Fixture para instância do RobotTrader"""
        config = {
            'api_key': 'test_key',
            'secret_key': 'test_secret',
            'max_position_size': 0.1,
            'risk_per_trade': 0.02,
            'stop_loss': 0.02,
            'take_profit': 0.04
        }
        return RobotTrader(config)
    
    @pytest.fixture
    def sample_market_data(self):
        """Fixture com dados de mercado de exemplo"""
        dates = pd.date_range(start='2024-01-01', periods=100, freq='1H')
        data = {
            'timestamp': dates,
            'open': np.random.uniform(50000, 51000, 100),
            'high': np.random.uniform(50500, 51500, 100),
            'low': np.random.uniform(49500, 50500, 100),
            'close': np.random.uniform(50000, 51000, 100),
            'volume': np.random.uniform(1000, 5000, 100)
        }
        return pd.DataFrame(data)
    
    def test_robot_trader_initialization(self, robot_trader):
        """Testar inicialização do RobotTrader"""
        assert robot_trader is not None
        assert robot_trader.config['max_position_size'] == 0.1
        assert robot_trader.config['risk_per_trade'] == 0.02
        assert robot_trader.is_running == False
    
    @pytest.mark.asyncio
    async def test_start_trading(self, robot_trader):
        """Testar início do trading"""
        with patch.object(robot_trader, '_trading_loop') as mock_loop:
            mock_loop.return_value = AsyncMock()
            await robot_trader.start_trading()
            assert robot_trader.is_running == True
            mock_loop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stop_trading(self, robot_trader):
        """Testar parada do trading"""
        robot_trader.is_running = True
        await robot_trader.stop_trading()
        assert robot_trader.is_running == False
    
    @pytest.mark.asyncio
    async def test_execute_trade_success(self, robot_trader):
        """Testar execução de trade bem-sucedida"""
        trade_signal = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.001,
            'price': 50000,
            'confidence': 0.8
        }
        
        with patch.object(robot_trader.broker, 'place_order') as mock_order:
            mock_order.return_value = {
                'id': 'order_123',
                'status': 'filled',
                'executed_qty': 0.001,
                'executed_price': 50000
            }
            
            result = await robot_trader.execute_trade(trade_signal)
            
            assert result['status'] == 'success'
            assert result['order_id'] == 'order_123'
            mock_order.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_trade_failure(self, robot_trader):
        """Testar falha na execução de trade"""
        trade_signal = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.001,
            'price': 50000,
            'confidence': 0.8
        }
        
        with patch.object(robot_trader.broker, 'place_order') as mock_order:
            mock_order.side_effect = Exception("Insufficient balance")
            
            result = await robot_trader.execute_trade(trade_signal)
            
            assert result['status'] == 'error'
            assert 'Insufficient balance' in result['message']
    
    def test_calculate_position_size(self, robot_trader):
        """Testar cálculo do tamanho da posição"""
        account_balance = 10000
        risk_per_trade = 0.02
        entry_price = 50000
        stop_loss_price = 49000
        
        position_size = robot_trader.calculate_position_size(
            account_balance, risk_per_trade, entry_price, stop_loss_price
        )
        
        expected_size = (account_balance * risk_per_trade) / (entry_price - stop_loss_price)
        assert abs(position_size - expected_size) < 0.001
    
    def test_validate_trade_signal(self, robot_trader):
        """Testar validação de sinal de trade"""
        valid_signal = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.001,
            'price': 50000,
            'confidence': 0.8
        }
        
        invalid_signal = {
            'symbol': 'BTC/USDT',
            'side': 'invalid_side',
            'quantity': -0.001,
            'price': 0,
            'confidence': 1.5
        }
        
        assert robot_trader.validate_trade_signal(valid_signal) == True
        assert robot_trader.validate_trade_signal(invalid_signal) == False

class TestAIModel:
    """Testes para o modelo de IA"""
    
    @pytest.fixture
    def ai_model(self):
        """Fixture para instância do AIModel"""
        config = {
            'model_type': 'hybrid_cnn_lstm_transformer',
            'sequence_length': 60,
            'features': ['open', 'high', 'low', 'close', 'volume'],
            'prediction_horizon': 1
        }
        return AIModel(config)
    
    @pytest.fixture
    def sample_training_data(self):
        """Fixture com dados de treinamento"""
        np.random.seed(42)
        n_samples = 1000
        n_features = 5
        
        X = np.random.randn(n_samples, 60, n_features)
        y = np.random.randint(0, 3, n_samples)  # 0: sell, 1: hold, 2: buy
        
        return X, y
    
    def test_ai_model_initialization(self, ai_model):
        """Testar inicialização do modelo de IA"""
        assert ai_model is not None
        assert ai_model.config['sequence_length'] == 60
        assert len(ai_model.config['features']) == 5
    
    def test_preprocess_data(self, ai_model, sample_market_data):
        """Testar pré-processamento de dados"""
        processed_data = ai_model.preprocess_data(sample_market_data)
        
        assert processed_data is not None
        assert len(processed_data.shape) == 3  # (samples, sequence_length, features)
        assert processed_data.shape[1] == ai_model.config['sequence_length']
        assert processed_data.shape[2] == len(ai_model.config['features'])
    
    @pytest.mark.asyncio
    async def test_train_model(self, ai_model, sample_training_data):
        """Testar treinamento do modelo"""
        X, y = sample_training_data
        
        with patch.object(ai_model, '_build_model') as mock_build:
            mock_model = Mock()
            mock_model.fit.return_value = Mock()
            mock_build.return_value = mock_model
            
            result = await ai_model.train(X, y)
            
            assert result['status'] == 'success'
            assert 'training_time' in result
            mock_model.fit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_predict(self, ai_model, sample_market_data):
        """Testar predição do modelo"""
        # Mock do modelo treinado
        ai_model.model = Mock()
        ai_model.model.predict.return_value = np.array([[0.1, 0.2, 0.7]])
        ai_model.is_trained = True
        
        prediction = await ai_model.predict(sample_market_data.tail(60))
        
        assert prediction is not None
        assert 'signal' in prediction
        assert 'confidence' in prediction
        assert prediction['signal'] in ['buy', 'sell', 'hold']
        assert 0 <= prediction['confidence'] <= 1
    
    def test_evaluate_model(self, ai_model, sample_training_data):
        """Testar avaliação do modelo"""
        X, y = sample_training_data
        
        # Mock do modelo treinado
        ai_model.model = Mock()
        ai_model.model.predict.return_value = np.random.randint(0, 3, len(y))
        ai_model.is_trained = True
        
        metrics = ai_model.evaluate(X, y)
        
        assert 'accuracy' in metrics
        assert 'precision' in metrics
        assert 'recall' in metrics
        assert 'f1_score' in metrics
        assert all(0 <= v <= 1 for v in metrics.values())

class TestRiskManager:
    """Testes para o gerenciador de risco"""
    
    @pytest.fixture
    def risk_manager(self):
        """Fixture para instância do RiskManager"""
        config = {
            'max_portfolio_risk': 0.02,
            'max_position_size': 0.1,
            'max_drawdown': 0.1,
            'max_daily_trades': 100,
            'stop_loss_percentage': 0.02,
            'take_profit_percentage': 0.04
        }
        return RiskManager(config)
    
    @pytest.fixture
    def sample_portfolio(self):
        """Fixture com portfólio de exemplo"""
        return {
            'total_value': 10000,
            'available_balance': 5000,
            'positions': [
                {'symbol': 'BTC/USDT', 'quantity': 0.1, 'entry_price': 50000, 'current_price': 51000},
                {'symbol': 'ETH/USDT', 'quantity': 1.0, 'entry_price': 3000, 'current_price': 3100}
            ],
            'daily_trades': 15,
            'max_drawdown': 0.05
        }
    
    def test_risk_manager_initialization(self, risk_manager):
        """Testar inicialização do RiskManager"""
        assert risk_manager is not None
        assert risk_manager.config['max_portfolio_risk'] == 0.02
        assert risk_manager.config['max_position_size'] == 0.1
    
    def test_check_position_size_risk(self, risk_manager, sample_portfolio):
        """Testar verificação de risco do tamanho da posição"""
        trade_signal = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.05,  # 5% do portfólio
            'price': 50000
        }
        
        result = risk_manager.check_position_size_risk(trade_signal, sample_portfolio)
        assert result['allowed'] == True
        
        # Testar com posição muito grande
        trade_signal['quantity'] = 0.15  # 15% do portfólio
        result = risk_manager.check_position_size_risk(trade_signal, sample_portfolio)
        assert result['allowed'] == False
    
    def test_check_portfolio_risk(self, risk_manager, sample_portfolio):
        """Testar verificação de risco do portfólio"""
        result = risk_manager.check_portfolio_risk(sample_portfolio)
        
        assert 'total_risk' in result
        assert 'max_drawdown' in result
        assert 'risk_level' in result
        assert result['risk_level'] in ['low', 'medium', 'high', 'critical']
    
    def test_check_daily_trade_limit(self, risk_manager, sample_portfolio):
        """Testar verificação do limite diário de trades"""
        result = risk_manager.check_daily_trade_limit(sample_portfolio)
        assert result['allowed'] == True
        
        # Testar com muitos trades
        sample_portfolio['daily_trades'] = 150
        result = risk_manager.check_daily_trade_limit(sample_portfolio)
        assert result['allowed'] == False
    
    def test_calculate_stop_loss_take_profit(self, risk_manager):
        """Testar cálculo de stop loss e take profit"""
        entry_price = 50000
        side = 'buy'
        
        levels = risk_manager.calculate_stop_loss_take_profit(entry_price, side)
        
        assert 'stop_loss' in levels
        assert 'take_profit' in levels
        
        # Para compra, stop loss deve ser menor que preço de entrada
        assert levels['stop_loss'] < entry_price
        assert levels['take_profit'] > entry_price
    
    def test_validate_trade_risk(self, risk_manager, sample_portfolio):
        """Testar validação completa de risco do trade"""
        trade_signal = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.05,
            'price': 50000,
            'confidence': 0.8
        }
        
        result = risk_manager.validate_trade_risk(trade_signal, sample_portfolio)
        
        assert 'allowed' in result
        assert 'risk_score' in result
        assert 'warnings' in result
        assert isinstance(result['warnings'], list)

class TestMarketDataManager:
    """Testes para o gerenciador de dados de mercado"""
    
    @pytest.fixture
    def market_data_manager(self):
        """Fixture para instância do MarketDataManager"""
        config = {
            'sources': ['binance', 'alpha_vantage'],
            'symbols': ['BTC/USDT', 'ETH/USDT'],
            'update_interval': 5,
            'historical_days': 30
        }
        return MarketDataManager(config)
    
    def test_market_data_manager_initialization(self, market_data_manager):
        """Testar inicialização do MarketDataManager"""
        assert market_data_manager is not None
        assert len(market_data_manager.config['sources']) == 2
        assert len(market_data_manager.config['symbols']) == 2
    
    @pytest.mark.asyncio
    async def test_fetch_real_time_data(self, market_data_manager):
        """Testar busca de dados em tempo real"""
        with patch.object(market_data_manager, '_fetch_from_source') as mock_fetch:
            mock_fetch.return_value = {
                'symbol': 'BTC/USDT',
                'price': 50000,
                'volume': 1000,
                'timestamp': datetime.utcnow()
            }
            
            data = await market_data_manager.fetch_real_time_data('BTC/USDT')
            
            assert data is not None
            assert data['symbol'] == 'BTC/USDT'
            assert data['price'] == 50000
            mock_fetch.assert_called()
    
    @pytest.mark.asyncio
    async def test_fetch_historical_data(self, market_data_manager):
        """Testar busca de dados históricos"""
        with patch.object(market_data_manager, '_fetch_historical_from_source') as mock_fetch:
            mock_data = pd.DataFrame({
                'timestamp': pd.date_range(start='2024-01-01', periods=100, freq='1H'),
                'open': np.random.uniform(49000, 51000, 100),
                'high': np.random.uniform(50000, 52000, 100),
                'low': np.random.uniform(48000, 50000, 100),
                'close': np.random.uniform(49000, 51000, 100),
                'volume': np.random.uniform(1000, 5000, 100)
            })
            mock_fetch.return_value = mock_data
            
            data = await market_data_manager.fetch_historical_data('BTC/USDT', '1h', 100)
            
            assert data is not None
            assert len(data) == 100
            assert all(col in data.columns for col in ['open', 'high', 'low', 'close', 'volume'])
    
    def test_validate_data_quality(self, market_data_manager):
        """Testar validação da qualidade dos dados"""
        # Dados válidos
        valid_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=10, freq='1H'),
            'open': [50000] * 10,
            'high': [51000] * 10,
            'low': [49000] * 10,
            'close': [50500] * 10,
            'volume': [1000] * 10
        })
        
        result = market_data_manager.validate_data_quality(valid_data)
        assert result['is_valid'] == True
        assert len(result['issues']) == 0
        
        # Dados inválidos
        invalid_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=10, freq='1H'),
            'open': [50000] * 10,
            'high': [49000] * 10,  # High menor que open (inválido)
            'low': [51000] * 10,   # Low maior que open (inválido)
            'close': [50500] * 10,
            'volume': [-1000] * 10  # Volume negativo (inválido)
        })
        
        result = market_data_manager.validate_data_quality(invalid_data)
        assert result['is_valid'] == False
        assert len(result['issues']) > 0

class TestBrokerAPI:
    """Testes para a API do broker"""
    
    @pytest.fixture
    def broker_api(self):
        """Fixture para instância do BrokerAPI"""
        config = {
            'api_key': 'test_key',
            'secret_key': 'test_secret',
            'sandbox': True,
            'base_url': 'https://testnet.binance.vision'
        }
        return BrokerAPI(config)
    
    def test_broker_api_initialization(self, broker_api):
        """Testar inicialização do BrokerAPI"""
        assert broker_api is not None
        assert broker_api.config['sandbox'] == True
        assert broker_api.is_connected == False
    
    @pytest.mark.asyncio
    async def test_connect(self, broker_api):
        """Testar conexão com o broker"""
        with patch.object(broker_api, '_test_connection') as mock_test:
            mock_test.return_value = True
            
            result = await broker_api.connect()
            
            assert result == True
            assert broker_api.is_connected == True
            mock_test.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_place_order_success(self, broker_api):
        """Testar colocação de ordem bem-sucedida"""
        broker_api.is_connected = True
        
        order_data = {
            'symbol': 'BTCUSDT',
            'side': 'BUY',
            'type': 'MARKET',
            'quantity': 0.001
        }
        
        with patch.object(broker_api, '_send_request') as mock_request:
            mock_request.return_value = {
                'orderId': 123456,
                'status': 'FILLED',
                'executedQty': '0.001',
                'cummulativeQuoteQty': '50.0'
            }
            
            result = await broker_api.place_order(order_data)
            
            assert result['orderId'] == 123456
            assert result['status'] == 'FILLED'
            mock_request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_account_info(self, broker_api):
        """Testar obtenção de informações da conta"""
        broker_api.is_connected = True
        
        with patch.object(broker_api, '_send_request') as mock_request:
            mock_request.return_value = {
                'totalWalletBalance': '10000.0',
                'availableBalance': '5000.0',
                'positions': []
            }
            
            result = await broker_api.get_account_info()
            
            assert float(result['totalWalletBalance']) == 10000.0
            assert float(result['availableBalance']) == 5000.0
            mock_request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_order_status(self, broker_api):
        """Testar obtenção do status da ordem"""
        broker_api.is_connected = True
        
        with patch.object(broker_api, '_send_request') as mock_request:
            mock_request.return_value = {
                'orderId': 123456,
                'status': 'FILLED',
                'executedQty': '0.001',
                'avgPrice': '50000.0'
            }
            
            result = await broker_api.get_order_status('BTCUSDT', 123456)
            
            assert result['orderId'] == 123456
            assert result['status'] == 'FILLED'
            mock_request.assert_called_once()

# Configuração do pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

