"""
API Routes para RoboTrader - Monitoramento e Controle
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import sys
import os
import asyncio
import threading
import json

# Adicionar o diretório pai ao path para importar módulos do RoboTrader
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    from database import db_manager
    from config import config
    from main_unified import RoboTraderUnified
except ImportError as e:
    print(f"Erro ao importar módulos do RoboTrader: {e}")
    db_manager = None
    config = None
    RoboTraderUnified = None

robotrader_bp = Blueprint('robotrader', __name__)

# Instância global do RoboTrader (será inicializada quando necessário)
robot_instance = None
robot_thread = None
robot_running = False

@robotrader_bp.route('/status', methods=['GET'])
def get_status():
    """Retorna status atual do RoboTrader"""
    try:
        global robot_running, robot_instance
        
        status = {
            'running': robot_running,
            'timestamp': datetime.now().isoformat(),
            'version': '3.0-unified',
            'components': {
                'database': db_manager is not None,
                'config': config is not None,
                'robot_class': RoboTraderUnified is not None
            }
        }
        
        if robot_instance:
            status['performance'] = robot_instance.performance_metrics
        
        return jsonify(status)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/start', methods=['POST'])
def start_robot():
    """Inicia o RoboTrader"""
    try:
        global robot_instance, robot_thread, robot_running
        
        if robot_running:
            return jsonify({'message': 'RoboTrader já está rodando'}), 400
        
        if not RoboTraderUnified:
            return jsonify({'error': 'RoboTrader não disponível'}), 500
        
        # Criar nova instância
        robot_instance = RoboTraderUnified()
        
        # Função para rodar o robot em thread separada
        def run_robot():
            global robot_running
            robot_running = True
            try:
                # Criar novo event loop para a thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(robot_instance.run())
            except Exception as e:
                print(f"Erro no RoboTrader: {e}")
            finally:
                robot_running = False
        
        # Iniciar thread
        robot_thread = threading.Thread(target=run_robot, daemon=True)
        robot_thread.start()
        
        return jsonify({
            'message': 'RoboTrader iniciado com sucesso',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/stop', methods=['POST'])
def stop_robot():
    """Para o RoboTrader"""
    try:
        global robot_instance, robot_running
        
        if not robot_running:
            return jsonify({'message': 'RoboTrader não está rodando'}), 400
        
        if robot_instance:
            robot_instance.shutdown_requested = True
            robot_instance.is_running = False
        
        robot_running = False
        
        return jsonify({
            'message': 'RoboTrader parado com sucesso',
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/metrics', methods=['GET'])
def get_metrics():
    """Retorna métricas de performance"""
    try:
        if not db_manager:
            return jsonify({'error': 'Database não disponível'}), 500
        
        # Parâmetros da query
        days = request.args.get('days', 30, type=int)
        
        # Obter métricas do banco
        metrics = db_manager.get_performance_metrics(days=days)
        
        # Adicionar métricas em tempo real se o robot estiver rodando
        if robot_instance and robot_running:
            metrics['real_time'] = robot_instance.performance_metrics
        
        return jsonify(metrics)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/trades', methods=['GET'])
def get_trades():
    """Retorna histórico de trades"""
    try:
        if not db_manager:
            return jsonify({'error': 'Database não disponível'}), 500
        
        # Parâmetros da query
        symbol = request.args.get('symbol')
        status = request.args.get('status')
        limit = request.args.get('limit', 100, type=int)
        days = request.args.get('days', 30, type=int)
        
        # Calcular data de início
        start_date = datetime.now() - timedelta(days=days)
        
        # Obter trades
        trades = db_manager.get_trades(
            symbol=symbol,
            start_date=start_date,
            status=status,
            limit=limit
        )
        
        # Converter para formato JSON
        trades_data = []
        for trade in trades:
            trades_data.append({
                'id': trade.id,
                'timestamp': trade.timestamp.isoformat(),
                'symbol': trade.symbol,
                'side': trade.side,
                'amount': trade.amount,
                'price': trade.price,
                'total_value': trade.total_value,
                'fees': trade.fees,
                'pnl': trade.pnl,
                'strategy': trade.strategy,
                'confidence': trade.confidence,
                'ai_signal': trade.ai_signal,
                'quantum_signal': trade.quantum_signal,
                'news_sentiment': trade.news_sentiment,
                'risk_score': trade.risk_score,
                'status': trade.status
            })
        
        return jsonify({
            'trades': trades_data,
            'total': len(trades_data),
            'filters': {
                'symbol': symbol,
                'status': status,
                'days': days,
                'limit': limit
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/portfolio', methods=['GET'])
def get_portfolio():
    """Retorna portfolio atual"""
    try:
        if not db_manager:
            return jsonify({'error': 'Database não disponível'}), 500
        
        portfolio = db_manager.get_portfolio()
        
        return jsonify({
            'portfolio': portfolio,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/market-data/<symbol>', methods=['GET'])
def get_market_data(symbol):
    """Retorna dados de mercado para um símbolo"""
    try:
        if not db_manager:
            return jsonify({'error': 'Database não disponível'}), 500
        
        # Parâmetros da query
        timeframe = request.args.get('timeframe', '1m')
        days = request.args.get('days', 7, type=int)
        limit = request.args.get('limit', 1000, type=int)
        
        # Calcular data de início
        start_date = datetime.now() - timedelta(days=days)
        
        # Obter dados
        data = db_manager.get_market_data(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            limit=limit
        )
        
        if data.empty:
            return jsonify({
                'symbol': symbol,
                'data': [],
                'message': 'Nenhum dado encontrado'
            })
        
        # Converter para formato JSON
        data_json = data.to_dict('records')
        for record in data_json:
            if 'timestamp' in record:
                record['timestamp'] = record['timestamp'].isoformat()
        
        return jsonify({
            'symbol': symbol,
            'timeframe': timeframe,
            'data': data_json,
            'total': len(data_json)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/config', methods=['GET'])
def get_config():
    """Retorna configuração atual"""
    try:
        if not config:
            return jsonify({'error': 'Config não disponível'}), 500
        
        # Converter config para dict (removendo informações sensíveis)
        config_dict = {
            'data': {
                'symbols': config.data.symbols,
                'timeframes': config.data.timeframes,
                'lookback_days': config.data.lookback_days
            },
            'trading': {
                'min_confidence': config.trading.min_confidence,
                'max_position_size': config.trading.max_position_size,
                'min_trade_amount': config.trading.min_trade_amount
            },
            'ai': {
                'sequence_length': config.ai.sequence_length,
                'batch_size': config.ai.batch_size,
                'epochs': config.ai.epochs
            },
            'api': {
                'exchange_name': config.api.exchange_name,
                'data_fetch_interval_seconds': config.api.data_fetch_interval_seconds
            }
        }
        
        return jsonify(config_dict)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/logs', methods=['GET'])
def get_logs():
    """Retorna logs recentes (simulado)"""
    try:
        # Em uma implementação real, isso leria arquivos de log
        logs = [
            {
                'timestamp': datetime.now().isoformat(),
                'level': 'INFO',
                'message': 'Sistema funcionando normalmente',
                'component': 'main'
            },
            {
                'timestamp': (datetime.now() - timedelta(minutes=1)).isoformat(),
                'level': 'INFO',
                'message': 'Análise de mercado concluída',
                'component': 'ai_model'
            },
            {
                'timestamp': (datetime.now() - timedelta(minutes=2)).isoformat(),
                'level': 'DEBUG',
                'message': 'Dados de mercado atualizados',
                'component': 'broker_api'
            }
        ]
        
        return jsonify({
            'logs': logs,
            'total': len(logs)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@robotrader_bp.route('/health', methods=['GET'])
def health_check():
    """Health check da API"""
    try:
        health = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'components': {
                'database': 'ok' if db_manager else 'error',
                'config': 'ok' if config else 'error',
                'robot': 'running' if robot_running else 'stopped'
            }
        }
        
        # Verificar conectividade do banco
        if db_manager:
            try:
                # Teste simples de conectividade
                metrics = db_manager.get_performance_metrics(days=1)
                health['components']['database'] = 'ok'
            except:
                health['components']['database'] = 'error'
        
        # Determinar status geral
        if all(status in ['ok', 'running', 'stopped'] for status in health['components'].values()):
            health['status'] = 'healthy'
        else:
            health['status'] = 'degraded'
        
        return jsonify(health)
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

