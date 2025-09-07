"""
Testes de Performance - RoboTrader 2.0
Testa a performance e capacidade do sistema sob diferentes cargas
"""

import pytest
import asyncio
import aiohttp
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json
import websockets
from locust import HttpUser, task, between
import threading
import queue

# Configuração de testes de performance
PERFORMANCE_CONFIG = {
    'api_base_url': 'http://localhost:5000',
    'websocket_url': 'ws://localhost:5000/socket.io',
    'concurrent_users': [1, 5, 10, 25, 50, 100],
    'test_duration': 60,  # segundos
    'acceptable_response_time': 2.0,  # segundos
    'acceptable_error_rate': 0.05,  # 5%
    'memory_limit_mb': 2048,
    'cpu_limit_percent': 80
}

class PerformanceMetrics:
    """Classe para coletar e analisar métricas de performance"""
    
    def __init__(self):
        self.response_times = []
        self.error_count = 0
        self.success_count = 0
        self.start_time = None
        self.end_time = None
        self.memory_usage = []
        self.cpu_usage = []
    
    def start_monitoring(self):
        """Iniciar monitoramento de recursos"""
        self.start_time = time.time()
        self.monitor_thread = threading.Thread(target=self._monitor_resources, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Parar monitoramento de recursos"""
        self.end_time = time.time()
    
    def _monitor_resources(self):
        """Monitorar uso de recursos do sistema"""
        while self.end_time is None:
            self.memory_usage.append(psutil.virtual_memory().percent)
            self.cpu_usage.append(psutil.cpu_percent(interval=1))
            time.sleep(1)
    
    def record_response(self, response_time, success=True):
        """Registrar tempo de resposta"""
        self.response_times.append(response_time)
        if success:
            self.success_count += 1
        else:
            self.error_count += 1
    
    def get_summary(self):
        """Obter resumo das métricas"""
        total_requests = self.success_count + self.error_count
        duration = self.end_time - self.start_time if self.end_time else 0
        
        return {
            'total_requests': total_requests,
            'success_rate': self.success_count / total_requests if total_requests > 0 else 0,
            'error_rate': self.error_count / total_requests if total_requests > 0 else 0,
            'requests_per_second': total_requests / duration if duration > 0 else 0,
            'avg_response_time': statistics.mean(self.response_times) if self.response_times else 0,
            'median_response_time': statistics.median(self.response_times) if self.response_times else 0,
            'p95_response_time': np.percentile(self.response_times, 95) if self.response_times else 0,
            'p99_response_time': np.percentile(self.response_times, 99) if self.response_times else 0,
            'max_response_time': max(self.response_times) if self.response_times else 0,
            'min_response_time': min(self.response_times) if self.response_times else 0,
            'avg_memory_usage': statistics.mean(self.memory_usage) if self.memory_usage else 0,
            'max_memory_usage': max(self.memory_usage) if self.memory_usage else 0,
            'avg_cpu_usage': statistics.mean(self.cpu_usage) if self.cpu_usage else 0,
            'max_cpu_usage': max(self.cpu_usage) if self.cpu_usage else 0,
            'duration': duration
        }

class TestAPIPerformance:
    """Testes de performance da API"""
    
    @pytest.mark.asyncio
    async def test_api_response_time_under_load(self):
        """Testar tempo de resposta da API sob carga"""
        metrics = PerformanceMetrics()
        metrics.start_monitoring()
        
        async def make_request(session, endpoint):
            start_time = time.time()
            try:
                async with session.get(f"{PERFORMANCE_CONFIG['api_base_url']}{endpoint}") as response:
                    await response.text()
                    response_time = time.time() - start_time
                    success = response.status == 200
                    metrics.record_response(response_time, success)
            except Exception:
                response_time = time.time() - start_time
                metrics.record_response(response_time, False)
        
        # Testar com diferentes níveis de concorrência
        for concurrent_users in PERFORMANCE_CONFIG['concurrent_users']:
            print(f"\nTesting with {concurrent_users} concurrent users...")
            
            async with aiohttp.ClientSession() as session:
                tasks = []
                for _ in range(concurrent_users * 10):  # 10 requests per user
                    task = make_request(session, '/health')
                    tasks.append(task)
                
                await asyncio.gather(*tasks)
        
        metrics.stop_monitoring()
        summary = metrics.get_summary()
        
        print(f"\nAPI Performance Summary:")
        print(f"Total Requests: {summary['total_requests']}")
        print(f"Success Rate: {summary['success_rate']:.2%}")
        print(f"Requests/Second: {summary['requests_per_second']:.2f}")
        print(f"Average Response Time: {summary['avg_response_time']:.3f}s")
        print(f"95th Percentile: {summary['p95_response_time']:.3f}s")
        print(f"Max Response Time: {summary['max_response_time']:.3f}s")
        
        # Assertions
        assert summary['success_rate'] >= (1 - PERFORMANCE_CONFIG['acceptable_error_rate'])
        assert summary['p95_response_time'] <= PERFORMANCE_CONFIG['acceptable_response_time']
        assert summary['max_memory_usage'] <= PERFORMANCE_CONFIG['memory_limit_mb'] / 1024 * 100  # Convert to percentage
    
    @pytest.mark.asyncio
    async def test_trading_endpoint_performance(self):
        """Testar performance dos endpoints de trading"""
        metrics = PerformanceMetrics()
        metrics.start_monitoring()
        
        # Simular dados de autenticação
        auth_headers = {'Authorization': 'Bearer test_token'}
        
        async def execute_trade_request(session):
            trade_data = {
                'symbol': 'BTC/USDT',
                'side': 'buy',
                'quantity': 0.001,
                'type': 'market',
                'test': True
            }
            
            start_time = time.time()
            try:
                async with session.post(
                    f"{PERFORMANCE_CONFIG['api_base_url']}/trading/execute",
                    json=trade_data,
                    headers=auth_headers
                ) as response:
                    await response.text()
                    response_time = time.time() - start_time
                    success = response.status in [200, 201]
                    metrics.record_response(response_time, success)
            except Exception:
                response_time = time.time() - start_time
                metrics.record_response(response_time, False)
        
        # Executar múltiplas requisições de trading
        async with aiohttp.ClientSession() as session:
            tasks = []
            for _ in range(100):  # 100 trade requests
                task = execute_trade_request(session)
                tasks.append(task)
            
            await asyncio.gather(*tasks)
        
        metrics.stop_monitoring()
        summary = metrics.get_summary()
        
        print(f"\nTrading Endpoint Performance:")
        print(f"Success Rate: {summary['success_rate']:.2%}")
        print(f"Average Response Time: {summary['avg_response_time']:.3f}s")
        print(f"95th Percentile: {summary['p95_response_time']:.3f}s")
        
        # Trading endpoints should be fast and reliable
        assert summary['success_rate'] >= 0.95
        assert summary['p95_response_time'] <= 1.0  # Trading should be sub-second
    
    @pytest.mark.asyncio
    async def test_market_data_streaming_performance(self):
        """Testar performance do streaming de dados de mercado"""
        metrics = PerformanceMetrics()
        metrics.start_monitoring()
        
        message_count = 0
        latencies = []
        
        async def websocket_client():
            nonlocal message_count, latencies
            
            try:
                async with websockets.connect(PERFORMANCE_CONFIG['websocket_url']) as websocket:
                    # Subscrever dados de mercado
                    subscribe_msg = {
                        'type': 'subscribe',
                        'channel': 'market_data',
                        'symbols': ['BTC/USDT', 'ETH/USDT']
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    
                    # Receber mensagens por 30 segundos
                    start_time = time.time()
                    while time.time() - start_time < 30:
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                            data = json.loads(message)
                            
                            if data.get('type') == 'market_data':
                                message_count += 1
                                # Calcular latência se timestamp estiver disponível
                                if 'timestamp' in data:
                                    msg_time = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                                    latency = (datetime.utcnow() - msg_time.replace(tzinfo=None)).total_seconds()
                                    latencies.append(latency)
                        
                        except asyncio.TimeoutError:
                            continue
                            
            except Exception as e:
                print(f"WebSocket error: {e}")
        
        # Executar múltiplos clientes WebSocket
        tasks = []
        for _ in range(5):  # 5 concurrent WebSocket connections
            task = websocket_client()
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        metrics.stop_monitoring()
        
        print(f"\nWebSocket Performance:")
        print(f"Messages Received: {message_count}")
        print(f"Messages/Second: {message_count / 30:.2f}")
        if latencies:
            print(f"Average Latency: {statistics.mean(latencies):.3f}s")
            print(f"95th Percentile Latency: {np.percentile(latencies, 95):.3f}s")
        
        # WebSocket should handle high message throughput
        assert message_count > 100  # Should receive at least 100 messages in 30 seconds
        if latencies:
            assert statistics.mean(latencies) < 0.1  # Average latency should be < 100ms

class TestAIModelPerformance:
    """Testes de performance do modelo de IA"""
    
    def test_prediction_latency(self):
        """Testar latência das predições do modelo de IA"""
        # Simular dados de entrada
        sample_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2024-01-01', periods=60, freq='1H'),
            'open': np.random.uniform(49000, 51000, 60),
            'high': np.random.uniform(50000, 52000, 60),
            'low': np.random.uniform(48000, 50000, 60),
            'close': np.random.uniform(49000, 51000, 60),
            'volume': np.random.uniform(1000, 5000, 60)
        })
        
        prediction_times = []
        
        # Simular múltiplas predições
        for _ in range(100):
            start_time = time.time()
            
            # Mock da predição (em produção seria o modelo real)
            # Simular processamento
            time.sleep(0.01)  # 10ms de processamento simulado
            prediction = {
                'signal': np.random.choice(['buy', 'sell', 'hold']),
                'confidence': np.random.uniform(0.5, 1.0)
            }
            
            prediction_time = time.time() - start_time
            prediction_times.append(prediction_time)
        
        avg_time = statistics.mean(prediction_times)
        p95_time = np.percentile(prediction_times, 95)
        max_time = max(prediction_times)
        
        print(f"\nAI Model Performance:")
        print(f"Average Prediction Time: {avg_time:.3f}s")
        print(f"95th Percentile: {p95_time:.3f}s")
        print(f"Max Prediction Time: {max_time:.3f}s")
        print(f"Predictions/Second: {1/avg_time:.2f}")
        
        # AI predictions should be fast for real-time trading
        assert avg_time < 0.1  # Average should be < 100ms
        assert p95_time < 0.2   # 95th percentile should be < 200ms
        assert max_time < 0.5   # Max should be < 500ms
    
    def test_batch_prediction_throughput(self):
        """Testar throughput de predições em lote"""
        batch_sizes = [1, 10, 50, 100, 500]
        throughput_results = {}
        
        for batch_size in batch_sizes:
            # Simular dados em lote
            batch_data = []
            for _ in range(batch_size):
                data = pd.DataFrame({
                    'timestamp': pd.date_range(start='2024-01-01', periods=60, freq='1H'),
                    'open': np.random.uniform(49000, 51000, 60),
                    'high': np.random.uniform(50000, 52000, 60),
                    'low': np.random.uniform(48000, 50000, 60),
                    'close': np.random.uniform(49000, 51000, 60),
                    'volume': np.random.uniform(1000, 5000, 60)
                })
                batch_data.append(data)
            
            start_time = time.time()
            
            # Simular processamento em lote
            predictions = []
            for data in batch_data:
                # Mock da predição
                time.sleep(0.005)  # 5ms por predição
                prediction = {
                    'signal': np.random.choice(['buy', 'sell', 'hold']),
                    'confidence': np.random.uniform(0.5, 1.0)
                }
                predictions.append(prediction)
            
            total_time = time.time() - start_time
            throughput = batch_size / total_time
            throughput_results[batch_size] = throughput
            
            print(f"Batch Size {batch_size}: {throughput:.2f} predictions/second")
        
        # Throughput should scale reasonably with batch size
        assert throughput_results[100] > throughput_results[1]
        assert throughput_results[100] > 50  # Should handle at least 50 predictions/second

class TestDatabasePerformance:
    """Testes de performance do banco de dados"""
    
    @pytest.mark.asyncio
    async def test_database_query_performance(self):
        """Testar performance de consultas ao banco de dados"""
        # Mock de conexão com banco de dados
        query_times = []
        
        # Simular diferentes tipos de consultas
        queries = [
            "SELECT * FROM users WHERE id = $1",
            "SELECT * FROM trades WHERE user_id = $1 ORDER BY created_at DESC LIMIT 100",
            "SELECT symbol, COUNT(*) FROM trades GROUP BY symbol",
            "SELECT * FROM market_data WHERE symbol = $1 AND timestamp > $2",
            "INSERT INTO trades (user_id, symbol, side, quantity, price) VALUES ($1, $2, $3, $4, $5)"
        ]
        
        for query in queries:
            times = []
            for _ in range(50):  # 50 execuções de cada consulta
                start_time = time.time()
                
                # Simular execução da consulta
                if "SELECT" in query:
                    time.sleep(0.01)  # 10ms para SELECT
                elif "INSERT" in query:
                    time.sleep(0.005)  # 5ms para INSERT
                
                query_time = time.time() - start_time
                times.append(query_time)
            
            avg_time = statistics.mean(times)
            query_times.extend(times)
            
            print(f"Query: {query[:50]}...")
            print(f"  Average Time: {avg_time:.3f}s")
            print(f"  95th Percentile: {np.percentile(times, 95):.3f}s")
        
        overall_avg = statistics.mean(query_times)
        overall_p95 = np.percentile(query_times, 95)
        
        print(f"\nOverall Database Performance:")
        print(f"Average Query Time: {overall_avg:.3f}s")
        print(f"95th Percentile: {overall_p95:.3f}s")
        
        # Database queries should be fast
        assert overall_avg < 0.05  # Average should be < 50ms
        assert overall_p95 < 0.1   # 95th percentile should be < 100ms
    
    @pytest.mark.asyncio
    async def test_concurrent_database_operations(self):
        """Testar operações concorrentes no banco de dados"""
        metrics = PerformanceMetrics()
        metrics.start_monitoring()
        
        async def simulate_database_operation():
            # Simular operação de banco de dados
            start_time = time.time()
            
            # Mix de operações (70% SELECT, 20% INSERT, 10% UPDATE)
            operation_type = np.random.choice(['SELECT', 'INSERT', 'UPDATE'], p=[0.7, 0.2, 0.1])
            
            if operation_type == 'SELECT':
                time.sleep(0.01)  # 10ms
            elif operation_type == 'INSERT':
                time.sleep(0.005)  # 5ms
            else:  # UPDATE
                time.sleep(0.015)  # 15ms
            
            operation_time = time.time() - start_time
            metrics.record_response(operation_time, True)
        
        # Executar operações concorrentes
        tasks = []
        for _ in range(500):  # 500 operações concorrentes
            task = simulate_database_operation()
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        metrics.stop_monitoring()
        summary = metrics.get_summary()
        
        print(f"\nConcurrent Database Operations:")
        print(f"Total Operations: {summary['total_requests']}")
        print(f"Operations/Second: {summary['requests_per_second']:.2f}")
        print(f"Average Time: {summary['avg_response_time']:.3f}s")
        print(f"95th Percentile: {summary['p95_response_time']:.3f}s")
        
        # Should handle concurrent operations efficiently
        assert summary['requests_per_second'] > 100  # At least 100 ops/second
        assert summary['p95_response_time'] < 0.1    # 95th percentile < 100ms

class TestMemoryAndResourceUsage:
    """Testes de uso de memória e recursos"""
    
    def test_memory_usage_under_load(self):
        """Testar uso de memória sob carga"""
        initial_memory = psutil.virtual_memory().percent
        memory_readings = [initial_memory]
        
        # Simular carga de trabalho
        data_structures = []
        
        for i in range(100):
            # Simular criação de estruturas de dados (como dados de mercado)
            market_data = pd.DataFrame({
                'timestamp': pd.date_range(start='2024-01-01', periods=1000, freq='1min'),
                'price': np.random.uniform(49000, 51000, 1000),
                'volume': np.random.uniform(100, 1000, 1000)
            })
            data_structures.append(market_data)
            
            # Monitorar memória a cada 10 iterações
            if i % 10 == 0:
                current_memory = psutil.virtual_memory().percent
                memory_readings.append(current_memory)
                print(f"Iteration {i}: Memory usage {current_memory:.1f}%")
        
        final_memory = psutil.virtual_memory().percent
        memory_increase = final_memory - initial_memory
        
        print(f"\nMemory Usage Test:")
        print(f"Initial Memory: {initial_memory:.1f}%")
        print(f"Final Memory: {final_memory:.1f}%")
        print(f"Memory Increase: {memory_increase:.1f}%")
        print(f"Max Memory: {max(memory_readings):.1f}%")
        
        # Memory usage should be reasonable
        assert max(memory_readings) < 90  # Should not exceed 90% memory usage
        assert memory_increase < 20       # Should not increase by more than 20%
    
    def test_cpu_usage_under_load(self):
        """Testar uso de CPU sob carga"""
        cpu_readings = []
        
        def cpu_intensive_task():
            # Simular tarefa intensiva de CPU (como cálculos de IA)
            start_time = time.time()
            while time.time() - start_time < 1:  # 1 segundo de trabalho
                # Simular cálculos matemáticos
                result = sum(i**2 for i in range(1000))
        
        # Executar tarefas em paralelo
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            
            for _ in range(10):  # 10 tarefas
                future = executor.submit(cpu_intensive_task)
                futures.append(future)
                
                # Monitorar CPU
                cpu_percent = psutil.cpu_percent(interval=0.1)
                cpu_readings.append(cpu_percent)
            
            # Aguardar conclusão
            for future in as_completed(futures):
                future.result()
                cpu_percent = psutil.cpu_percent(interval=0.1)
                cpu_readings.append(cpu_percent)
        
        avg_cpu = statistics.mean(cpu_readings)
        max_cpu = max(cpu_readings)
        
        print(f"\nCPU Usage Test:")
        print(f"Average CPU: {avg_cpu:.1f}%")
        print(f"Max CPU: {max_cpu:.1f}%")
        
        # CPU usage should be manageable
        assert max_cpu < 95  # Should not max out CPU completely
        assert avg_cpu < 80  # Average should be reasonable

# Classe para testes de carga com Locust (opcional)
class RoboTraderUser(HttpUser):
    """Usuário simulado para testes de carga com Locust"""
    wait_time = between(1, 3)
    
    def on_start(self):
        """Executado quando o usuário inicia"""
        # Simular login
        response = self.client.post("/auth/login", json={
            "username": "test_user",
            "password": "test_password"
        })
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.headers = {}
    
    @task(3)
    def get_portfolio(self):
        """Obter informações do portfólio"""
        self.client.get("/portfolio", headers=self.headers)
    
    @task(2)
    def get_market_data(self):
        """Obter dados de mercado"""
        symbols = ["BTC/USDT", "ETH/USDT", "ADA/USDT"]
        symbol = np.random.choice(symbols)
        self.client.get(f"/market/realtime/{symbol.replace('/', '/')}")
    
    @task(1)
    def execute_trade(self):
        """Executar trade simulado"""
        trade_data = {
            "symbol": "BTC/USDT",
            "side": "buy",
            "quantity": 0.001,
            "type": "market",
            "test": True
        }
        self.client.post("/trading/execute", json=trade_data, headers=self.headers)
    
    @task(1)
    def get_ai_prediction(self):
        """Obter predição de IA"""
        self.client.get("/ai/predictions/BTC/USDT", headers=self.headers)

# Executar testes
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])

