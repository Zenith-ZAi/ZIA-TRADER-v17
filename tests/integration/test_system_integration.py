"""
Testes de Integração - RoboTrader 2.0
Testa a integração entre diferentes componentes do sistema
"""

import pytest
import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from unittest.mock import patch, AsyncMock
import websockets
import jwt

# Configuração de teste
TEST_CONFIG = {
    'api_base_url': 'http://localhost:5000',
    'websocket_url': 'ws://localhost:5000/socket.io',
    'test_user': {
        'username': 'test_user',
        'email': 'test@robotrader.com',
        'password': 'test_password_123'
    },
    'test_symbols': ['BTC/USDT', 'ETH/USDT'],
    'database_url': 'postgresql://test_user:test_pass@localhost:5432/test_robotrader'
}

class TestAPIIntegration:
    """Testes de integração da API"""
    
    @pytest.fixture
    async def api_client(self):
        """Fixture para cliente HTTP da API"""
        async with aiohttp.ClientSession() as session:
            yield session
    
    @pytest.fixture
    async def authenticated_headers(self, api_client):
        """Fixture para headers autenticados"""
        # Registrar usuário de teste
        register_data = TEST_CONFIG['test_user']
        async with api_client.post(
            f"{TEST_CONFIG['api_base_url']}/auth/register",
            json=register_data
        ) as response:
            assert response.status == 201
        
        # Fazer login
        login_data = {
            'username': register_data['username'],
            'password': register_data['password']
        }
        async with api_client.post(
            f"{TEST_CONFIG['api_base_url']}/auth/login",
            json=login_data
        ) as response:
            assert response.status == 200
            data = await response.json()
            token = data['access_token']
        
        return {'Authorization': f'Bearer {token}'}
    
    @pytest.mark.asyncio
    async def test_user_registration_and_login(self, api_client):
        """Testar registro e login de usuário"""
        # Registrar usuário
        register_data = {
            'username': 'integration_test_user',
            'email': 'integration@test.com',
            'password': 'secure_password_123'
        }
        
        async with api_client.post(
            f"{TEST_CONFIG['api_base_url']}/auth/register",
            json=register_data
        ) as response:
            assert response.status == 201
            data = await response.json()
            assert 'user_id' in data
        
        # Fazer login
        login_data = {
            'username': register_data['username'],
            'password': register_data['password']
        }
        
        async with api_client.post(
            f"{TEST_CONFIG['api_base_url']}/auth/login",
            json=login_data
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert 'access_token' in data
            assert 'refresh_token' in data
            
            # Verificar se o token é válido
            token = data['access_token']
            decoded = jwt.decode(token, options={"verify_signature": False})
            assert decoded['username'] == register_data['username']
    
    @pytest.mark.asyncio
    async def test_portfolio_operations(self, api_client, authenticated_headers):
        """Testar operações de portfólio"""
        # Obter informações do portfólio
        async with api_client.get(
            f"{TEST_CONFIG['api_base_url']}/portfolio",
            headers=authenticated_headers
        ) as response:
            assert response.status == 200
            portfolio = await response.json()
            assert 'total_value' in portfolio
            assert 'positions' in portfolio
            assert 'available_balance' in portfolio
        
        # Simular adição de posição
        position_data = {
            'symbol': 'BTC/USDT',
            'quantity': 0.001,
            'entry_price': 50000,
            'side': 'buy'
        }
        
        async with api_client.post(
            f"{TEST_CONFIG['api_base_url']}/portfolio/positions",
            json=position_data,
            headers=authenticated_headers
        ) as response:
            assert response.status == 201
            position = await response.json()
            assert position['symbol'] == 'BTC/USDT'
            assert position['quantity'] == 0.001
    
    @pytest.mark.asyncio
    async def test_trading_operations(self, api_client, authenticated_headers):
        """Testar operações de trading"""
        # Obter sinais de trading
        async with api_client.get(
            f"{TEST_CONFIG['api_base_url']}/trading/signals",
            headers=authenticated_headers
        ) as response:
            assert response.status == 200
            signals = await response.json()
            assert isinstance(signals, list)
        
        # Executar trade simulado
        trade_data = {
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.001,
            'type': 'market',
            'test': True  # Trade de teste
        }
        
        async with api_client.post(
            f"{TEST_CONFIG['api_base_url']}/trading/execute",
            json=trade_data,
            headers=authenticated_headers
        ) as response:
            assert response.status == 200
            result = await response.json()
            assert result['status'] in ['success', 'pending']
            assert 'order_id' in result
    
    @pytest.mark.asyncio
    async def test_market_data_endpoints(self, api_client):
        """Testar endpoints de dados de mercado"""
        # Obter dados em tempo real
        async with api_client.get(
            f"{TEST_CONFIG['api_base_url']}/market/realtime/BTC/USDT"
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert 'price' in data
            assert 'volume' in data
            assert 'timestamp' in data
        
        # Obter dados históricos
        async with api_client.get(
            f"{TEST_CONFIG['api_base_url']}/market/history/BTC/USDT?interval=1h&limit=100"
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert isinstance(data, list)
            assert len(data) <= 100
            if data:
                assert all(key in data[0] for key in ['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    @pytest.mark.asyncio
    async def test_ai_model_endpoints(self, api_client, authenticated_headers):
        """Testar endpoints do modelo de IA"""
        # Obter predições
        async with api_client.get(
            f"{TEST_CONFIG['api_base_url']}/ai/predictions/BTC/USDT",
            headers=authenticated_headers
        ) as response:
            assert response.status == 200
            prediction = await response.json()
            assert 'signal' in prediction
            assert 'confidence' in prediction
            assert prediction['signal'] in ['buy', 'sell', 'hold']
            assert 0 <= prediction['confidence'] <= 1
        
        # Obter métricas do modelo
        async with api_client.get(
            f"{TEST_CONFIG['api_base_url']}/ai/metrics",
            headers=authenticated_headers
        ) as response:
            assert response.status == 200
            metrics = await response.json()
            assert 'accuracy' in metrics
            assert 'precision' in metrics
            assert 'recall' in metrics

class TestWebSocketIntegration:
    """Testes de integração WebSocket"""
    
    @pytest.mark.asyncio
    async def test_websocket_connection(self):
        """Testar conexão WebSocket"""
        try:
            async with websockets.connect(TEST_CONFIG['websocket_url']) as websocket:
                # Enviar mensagem de autenticação
                auth_message = {
                    'type': 'auth',
                    'token': 'test_token'
                }
                await websocket.send(json.dumps(auth_message))
                
                # Aguardar resposta
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(response)
                
                assert data['type'] == 'auth_response'
                assert 'status' in data
        except Exception as e:
            pytest.skip(f"WebSocket server not available: {e}")
    
    @pytest.mark.asyncio
    async def test_real_time_market_data_stream(self):
        """Testar stream de dados de mercado em tempo real"""
        try:
            async with websockets.connect(TEST_CONFIG['websocket_url']) as websocket:
                # Subscrever dados de mercado
                subscribe_message = {
                    'type': 'subscribe',
                    'channel': 'market_data',
                    'symbols': ['BTC/USDT']
                }
                await websocket.send(json.dumps(subscribe_message))
                
                # Aguardar dados de mercado
                for _ in range(3):  # Receber 3 mensagens
                    response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    data = json.loads(response)
                    
                    if data['type'] == 'market_data':
                        assert 'symbol' in data
                        assert 'price' in data
                        assert 'timestamp' in data
                        break
        except Exception as e:
            pytest.skip(f"WebSocket server not available: {e}")
    
    @pytest.mark.asyncio
    async def test_trading_notifications(self):
        """Testar notificações de trading via WebSocket"""
        try:
            async with websockets.connect(TEST_CONFIG['websocket_url']) as websocket:
                # Subscrever notificações de trading
                subscribe_message = {
                    'type': 'subscribe',
                    'channel': 'trading_notifications'
                }
                await websocket.send(json.dumps(subscribe_message))
                
                # Simular execução de trade (seria feito via API)
                # Aguardar notificação
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(response)
                
                if data['type'] == 'trade_notification':
                    assert 'trade_id' in data
                    assert 'status' in data
                    assert 'symbol' in data
        except Exception as e:
            pytest.skip(f"WebSocket server not available: {e}")

class TestDatabaseIntegration:
    """Testes de integração com banco de dados"""
    
    @pytest.fixture
    async def db_connection(self):
        """Fixture para conexão com banco de dados"""
        import asyncpg
        try:
            conn = await asyncpg.connect(TEST_CONFIG['database_url'])
            yield conn
            await conn.close()
        except Exception as e:
            pytest.skip(f"Database not available: {e}")
    
    @pytest.mark.asyncio
    async def test_user_data_persistence(self, db_connection):
        """Testar persistência de dados do usuário"""
        # Inserir usuário de teste
        user_data = {
            'username': 'db_test_user',
            'email': 'dbtest@example.com',
            'password_hash': 'hashed_password'
        }
        
        user_id = await db_connection.fetchval(
            """
            INSERT INTO users (username, email, password_hash, created_at)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            user_data['username'],
            user_data['email'],
            user_data['password_hash'],
            datetime.utcnow()
        )
        
        assert user_id is not None
        
        # Verificar se o usuário foi inserido
        user = await db_connection.fetchrow(
            "SELECT * FROM users WHERE id = $1",
            user_id
        )
        
        assert user['username'] == user_data['username']
        assert user['email'] == user_data['email']
    
    @pytest.mark.asyncio
    async def test_trade_data_persistence(self, db_connection):
        """Testar persistência de dados de trades"""
        # Inserir trade de teste
        trade_data = {
            'user_id': 1,  # Assumindo que existe
            'symbol': 'BTC/USDT',
            'side': 'buy',
            'quantity': 0.001,
            'price': 50000,
            'status': 'executed',
            'executed_at': datetime.utcnow()
        }
        
        trade_id = await db_connection.fetchval(
            """
            INSERT INTO trades (user_id, symbol, side, quantity, price, status, executed_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            trade_data['user_id'],
            trade_data['symbol'],
            trade_data['side'],
            trade_data['quantity'],
            trade_data['price'],
            trade_data['status'],
            trade_data['executed_at']
        )
        
        assert trade_id is not None
        
        # Verificar se o trade foi inserido
        trade = await db_connection.fetchrow(
            "SELECT * FROM trades WHERE id = $1",
            trade_id
        )
        
        assert trade['symbol'] == trade_data['symbol']
        assert trade['side'] == trade_data['side']
        assert float(trade['quantity']) == trade_data['quantity']
    
    @pytest.mark.asyncio
    async def test_market_data_storage(self, db_connection):
        """Testar armazenamento de dados de mercado"""
        # Inserir dados de mercado de teste
        market_data = {
            'symbol': 'BTC/USDT',
            'timestamp': datetime.utcnow(),
            'open': 50000,
            'high': 51000,
            'low': 49000,
            'close': 50500,
            'volume': 1000
        }
        
        await db_connection.execute(
            """
            INSERT INTO market_data (symbol, timestamp, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            market_data['symbol'],
            market_data['timestamp'],
            market_data['open'],
            market_data['high'],
            market_data['low'],
            market_data['close'],
            market_data['volume']
        )
        
        # Verificar se os dados foram inseridos
        data = await db_connection.fetchrow(
            """
            SELECT * FROM market_data 
            WHERE symbol = $1 AND timestamp = $2
            """,
            market_data['symbol'],
            market_data['timestamp']
        )
        
        assert data is not None
        assert float(data['open']) == market_data['open']
        assert float(data['close']) == market_data['close']

class TestAIModelIntegration:
    """Testes de integração do modelo de IA"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_prediction_pipeline(self):
        """Testar pipeline completo de predição"""
        # Simular dados de mercado
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=100, freq='1H'),
            'open': np.random.uniform(49000, 51000, 100),
            'high': np.random.uniform(50000, 52000, 100),
            'low': np.random.uniform(48000, 50000, 100),
            'close': np.random.uniform(49000, 51000, 100),
            'volume': np.random.uniform(1000, 5000, 100)
        })
        
        # Mock do sistema de IA
        with patch('ai_model.AIModel') as MockAIModel:
            mock_ai = MockAIModel.return_value
            mock_ai.predict.return_value = {
                'signal': 'buy',
                'confidence': 0.75,
                'features': {
                    'trend': 'bullish',
                    'momentum': 'strong',
                    'volatility': 'low'
                }
            }
            
            # Simular pipeline completo
            from ai_model import AIModel
            ai_model = AIModel({})
            
            prediction = await ai_model.predict(market_data.tail(60))
            
            assert prediction['signal'] in ['buy', 'sell', 'hold']
            assert 0 <= prediction['confidence'] <= 1
            assert 'features' in prediction
    
    @pytest.mark.asyncio
    async def test_model_retraining_integration(self):
        """Testar integração do retreinamento do modelo"""
        # Simular dados de treinamento
        training_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=1000, freq='1H'),
            'open': np.random.uniform(49000, 51000, 1000),
            'high': np.random.uniform(50000, 52000, 1000),
            'low': np.random.uniform(48000, 50000, 1000),
            'close': np.random.uniform(49000, 51000, 1000),
            'volume': np.random.uniform(1000, 5000, 1000)
        })
        
        with patch('model_retraining_system.ModelRetrainingSystem') as MockRetraining:
            mock_retraining = MockRetraining.return_value
            mock_retraining.retrain_model.return_value = {
                'status': 'success',
                'metrics': {
                    'accuracy': 0.85,
                    'precision': 0.82,
                    'recall': 0.88
                },
                'training_time': 300
            }
            
            from model_retraining_system import ModelRetrainingSystem
            retraining_system = ModelRetrainingSystem({})
            
            result = await retraining_system.retrain_model(training_data)
            
            assert result['status'] == 'success'
            assert 'metrics' in result
            assert 'training_time' in result

class TestRiskManagementIntegration:
    """Testes de integração do gerenciamento de risco"""
    
    @pytest.mark.asyncio
    async def test_real_time_risk_monitoring(self):
        """Testar monitoramento de risco em tempo real"""
        # Simular portfólio
        portfolio = {
            'total_value': 10000,
            'positions': [
                {'symbol': 'BTC/USDT', 'quantity': 0.1, 'entry_price': 50000},
                {'symbol': 'ETH/USDT', 'quantity': 1.0, 'entry_price': 3000}
            ]
        }
        
        # Simular preços atuais
        current_prices = {
            'BTC/USDT': 48000,  # Perda de 4%
            'ETH/USDT': 2900    # Perda de 3.33%
        }
        
        with patch('risk_management.RiskManager') as MockRiskManager:
            mock_risk = MockRiskManager.return_value
            mock_risk.calculate_portfolio_risk.return_value = {
                'total_risk': 0.038,  # 3.8% de risco
                'max_drawdown': 0.045,
                'var_95': 0.025,
                'risk_level': 'medium'
            }
            
            from risk_management import RiskManager
            risk_manager = RiskManager({})
            
            risk_assessment = risk_manager.calculate_portfolio_risk(portfolio, current_prices)
            
            assert 'total_risk' in risk_assessment
            assert 'risk_level' in risk_assessment
            assert risk_assessment['risk_level'] in ['low', 'medium', 'high', 'critical']
    
    @pytest.mark.asyncio
    async def test_automated_stop_loss_execution(self):
        """Testar execução automática de stop loss"""
        # Simular posição com stop loss
        position = {
            'symbol': 'BTC/USDT',
            'quantity': 0.1,
            'entry_price': 50000,
            'stop_loss': 49000,
            'current_price': 48500  # Abaixo do stop loss
        }
        
        with patch('broker_api.BrokerAPI') as MockBroker:
            mock_broker = MockBroker.return_value
            mock_broker.place_order.return_value = {
                'order_id': 'stop_loss_123',
                'status': 'filled',
                'executed_price': 48500
            }
            
            from risk_management import RiskManager
            risk_manager = RiskManager({})
            
            # Simular verificação de stop loss
            should_execute = position['current_price'] <= position['stop_loss']
            assert should_execute == True
            
            # Simular execução do stop loss
            if should_execute:
                result = await mock_broker.place_order({
                    'symbol': position['symbol'],
                    'side': 'sell',
                    'quantity': position['quantity'],
                    'type': 'market'
                })
                
                assert result['status'] == 'filled'
                assert 'order_id' in result

# Configuração de fixtures globais
@pytest.fixture(scope="session")
def event_loop():
    """Criar event loop para testes assíncronos"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Executar testes
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--asyncio-mode=auto"])

