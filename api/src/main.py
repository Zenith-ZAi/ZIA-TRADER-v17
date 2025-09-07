import os
import sys
import logging
from datetime import datetime
from flask import Flask, send_from_directory, redirect, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import eventlet

from src.models.user import db
from src.routes.user import user_bp
from src.routes.robotrader import robotrader_bp
from src.config import config
from security_enhanced import (
    add_security_headers, 
    force_https, 
    validate_request_data,
    get_security_metrics,
    require_auth,
    advanced_rate_limit
)
from websocket_manager import initialize_websocket_manager, get_websocket_manager

# DON\'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Monkey patch para compatibilidade com SocketIO e asyncio
eventlet.monkey_patch()

# Configuração de logging
logging.basicConfig(
    level=getattr(logging, config.logging.level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), \'static\'))

# Configurações de segurança
app.config[\'SECRET_KEY\'] = config.security.jwt_secret_key
app.config[\'MAX_CONTENT_LENGTH\'] = 16 * 1024 * 1024  # 16MB max file size

# Configurar CORS com configurações de segurança
CORS(app, 
     origins=["http://localhost:3000", "https://localhost:3000"],  # Especificar origens permitidas
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# Configurar SocketIO com segurança aprimorada
socketio = SocketIO(
    app, 
    cors_allowed_origins=["http://localhost:3000", "https://localhost:3000"],
    async_mode=\'eventlet\',
    logger=True,
    engineio_logger=True
)

# Inicializar gerenciador WebSocket
ws_manager = initialize_websocket_manager(socketio)

# Forçar HTTPS em produção
if not config.api.sandbox_mode:
    force_https(app)

# Validar dados de requisição
validate_request_data()

# Adicionar headers de segurança a todas as respostas
@app.after_request
def apply_security_headers(response):
    return add_security_headers(response)

app.register_blueprint(user_bp, url_prefix=\'/api\')
app.register_blueprint(robotrader_bp, url_prefix=\'/api/robotrader\')

# Rotas de segurança e monitoramento
@app.route(\'/api/security/metrics\', methods=[\'GET\'])
@require_auth
@advanced_rate_limit(limit_per_minute=10)
def security_metrics():
    """Endpoint para métricas de segurança"""
    try:
        metrics = get_security_metrics()
        return jsonify(metrics), 200
    except Exception as e:
        return jsonify({"error": "Erro ao obter métricas de segurança"}), 500

@app.route(\'/api/websocket/stats\', methods=[\'GET\'])
@require_auth
@advanced_rate_limit(limit_per_minute=30)
def websocket_stats():
    """Endpoint para estatísticas do WebSocket"""
    try:
        if ws_manager:
            stats = ws_manager.get_statistics()
            return jsonify(stats), 200
        else:
            return jsonify({"error": "WebSocket manager não inicializado"}), 500
    except Exception as e:
        return jsonify({"error": "Erro ao obter estatísticas do WebSocket"}), 500

@app.route(\'/api/health\', methods=[\'GET\'])
@advanced_rate_limit(limit_per_minute=60)
def health_check():
    """Health check endpoint"""
    try:
        # Verificar componentes críticos
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "database": "healthy",
                "websocket": "healthy" if ws_manager else "unhealthy",
                "security": "healthy"
            }
        }
        
        # Verificar banco de dados
        try:
            db.session.execute(\'SELECT 1\')
            health_status["components"]["database"] = "healthy"
        except:
            health_status["components"]["database"] = "unhealthy"
            health_status["status"] = "degraded"
        
        status_code = 200 if health_status["status"] == "healthy" else 503
        return jsonify(health_status), status_code
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503

# uncomment if you need to use database
app.config[\'SQLALCHEMY_DATABASE_URI\'] = f"sqlite:///{os.path.join(os.path.dirname(__file__), \'database\', \'app.db\')}"
app.config[\'SQLALCHEMY_TRACK_MODIFICATIONS\'] = False
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route(\'/\', defaults={\'path\': \'\'}) 
@app.route(\'/<path:path>\')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
            return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, \'index.html\')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, \'index.html\')
        else:
            return "index.html not found", 404


if __name__ == \'__main__\':
    socketio.run(app, host=\'0.0.0.0\', port=5000, debug=True)



# Configuração do banco de dados
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'database', 'app.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar banco de dados
db.init_app(app)
with app.app_context():
    # Criar diretório de banco de dados se não existir
    db_dir = os.path.join(os.path.dirname(__file__), 'database')
    os.makedirs(db_dir, exist_ok=True)
    
    # Criar diretório de logs se não existir
    logs_dir = 'logs'
    os.makedirs(logs_dir, exist_ok=True)
    
    # Criar todas as tabelas
    db.create_all()

@app.route('/', defaults={'path': ''}) 
@app.route('/<path:path>')
def serve(path):
    """Servir arquivos estáticos do frontend"""
    static_folder_path = app.static_folder
    if static_folder_path is None:
        return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "index.html not found", 404

# Handler de erro global
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint não encontrado"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Erro interno do servidor"}), 500

@app.errorhandler(429)
def rate_limit_exceeded(error):
    return jsonify({"error": "Limite de requisições excedido"}), 429

if __name__ == '__main__':
    # Configurar logging para produção
    if not config.api.sandbox_mode:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    # Inicializar servidor
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=5000, 
        debug=config.api.sandbox_mode,
        use_reloader=False  # Evitar problemas com SocketIO
    )

