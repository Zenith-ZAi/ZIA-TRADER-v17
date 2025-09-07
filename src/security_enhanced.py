"""
Módulo de Segurança Aprimorado para RoboTrader 2.0
Implementa medidas de segurança avançadas para ambiente de produção
"""

import jwt
import redis
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from cryptography.fernet import Fernet
from passlib.context import CryptContext
from functools import wraps
from flask import request, jsonify, current_app, g
from flask_socketio import disconnect
from src.config import config
import ipaddress
import re

# Configuração do logger de segurança
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
handler = logging.FileHandler('logs/security_audit.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
security_logger.addHandler(handler)

# Configuração do Redis para rate limiting e blacklist (em produção)
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    security_logger.warning("Redis não disponível, usando cache em memória")

# Cache em memória como fallback
memory_cache = {
    'rate_limits': {},
    'blacklist': set(),
    'failed_attempts': {},
    'active_sessions': {}
}

# Configurações de segurança
SECRET_KEY = config.security.jwt_secret_key
ALGORITHM = config.security.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = config.security.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = config.security.refresh_token_expire_days

# Configuração de criptografia
DATA_ENCRYPTION_KEY = config.security.data_encryption_key.encode('utf-8')
fernet = Fernet(DATA_ENCRYPTION_KEY)

# Configuração de hash de senhas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Padrões de segurança
SUSPICIOUS_PATTERNS = [
    r'<script.*?>.*?</script>',
    r'javascript:',
    r'on\w+\s*=',
    r'eval\s*\(',
    r'document\.',
    r'window\.',
    r'alert\s*\(',
    r'confirm\s*\(',
    r'prompt\s*\(',
    r'<iframe',
    r'<object',
    r'<embed',
    r'<link',
    r'<meta',
    r'<style',
    r'expression\s*\(',
    r'url\s*\(',
    r'@import',
    r'vbscript:',
    r'data:text/html',
    r'data:application/javascript'
]

# Lista de IPs suspeitos (exemplo - em produção, usar serviços de threat intelligence)
SUSPICIOUS_IPS = {
    '127.0.0.1',  # Exemplo - remover em produção
}

class SecurityManager:
    """Gerenciador central de segurança"""
    
    def __init__(self):
        self.failed_login_attempts = {}
        self.active_sessions = {}
        self.security_events = []
    
    def log_security_event(self, event_type: str, details: Dict[str, Any], severity: str = "INFO"):
        """Log de eventos de segurança"""
        event = {
            'timestamp': datetime.utcnow().isoformat(),
            'type': event_type,
            'details': details,
            'severity': severity,
            'ip': request.remote_addr if request else 'system',
            'user_agent': request.headers.get('User-Agent', 'unknown') if request else 'system'
        }
        
        self.security_events.append(event)
        security_logger.info(f"SECURITY_EVENT: {event}")
        
        # Alertas críticos
        if severity in ['CRITICAL', 'HIGH']:
            self._send_security_alert(event)
    
    def _send_security_alert(self, event: Dict[str, Any]):
        """Enviar alertas de segurança críticos"""
        # Implementar notificações (email, Slack, etc.)
        security_logger.critical(f"CRITICAL_SECURITY_ALERT: {event}")

# Instância global do gerenciador de segurança
security_manager = SecurityManager()

def generate_secure_token() -> str:
    """Gerar token seguro"""
    return secrets.token_urlsafe(32)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Criar token de acesso JWT"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # Adicionar claims de segurança
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": generate_secure_token(),  # JWT ID único
        "iss": "robotrader-api",  # Issuer
        "aud": "robotrader-client"  # Audience
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    # Log da criação do token
    security_manager.log_security_event(
        "TOKEN_CREATED",
        {"user": data.get("sub"), "expires": expire.isoformat()}
    )
    
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Criar token de refresh JWT"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": generate_secure_token(),
        "type": "refresh",
        "iss": "robotrader-api",
        "aud": "robotrader-client"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """Verificar e decodificar token JWT"""
    try:
        payload = jwt.decode(
            token, 
            SECRET_KEY, 
            algorithms=[ALGORITHM],
            audience="robotrader-client",
            issuer="robotrader-api"
        )
        
        # Verificar se o token está na blacklist
        jti = payload.get('jti')
        if is_token_blacklisted(jti):
            security_manager.log_security_event(
                "BLACKLISTED_TOKEN_USED",
                {"jti": jti, "user": payload.get("sub")},
                "HIGH"
            )
            return {"error": "Token revogado"}
        
        return payload
    except jwt.ExpiredSignatureError:
        security_manager.log_security_event(
            "EXPIRED_TOKEN_USED",
            {"token_preview": token[:20] + "..."},
            "MEDIUM"
        )
        return {"error": "Token expirado"}
    except jwt.InvalidTokenError as e:
        security_manager.log_security_event(
            "INVALID_TOKEN_USED",
            {"error": str(e), "token_preview": token[:20] + "..."},
            "HIGH"
        )
        return {"error": "Token inválido"}

def blacklist_token(jti: str, expiry: Optional[datetime] = None):
    """Adicionar token à blacklist"""
    if REDIS_AVAILABLE:
        if expiry:
            ttl = int((expiry - datetime.utcnow()).total_seconds())
            redis_client.setex(f"blacklist:{jti}", ttl, "1")
        else:
            redis_client.set(f"blacklist:{jti}", "1")
    else:
        memory_cache['blacklist'].add(jti)

def is_token_blacklisted(jti: str) -> bool:
    """Verificar se token está na blacklist"""
    if REDIS_AVAILABLE:
        return redis_client.exists(f"blacklist:{jti}")
    else:
        return jti in memory_cache['blacklist']

def get_password_hash(password: str) -> str:
    """Hash de senha"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verificar senha"""
    return pwd_context.verify(plain_password, hashed_password)

def encrypt_data(data: str) -> str:
    """Criptografar dados sensíveis"""
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    """Descriptografar dados"""
    return fernet.decrypt(encrypted_data.encode()).decode()

def validate_input(data: str) -> bool:
    """Validar entrada contra padrões suspeitos"""
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, data, re.IGNORECASE):
            security_manager.log_security_event(
                "SUSPICIOUS_INPUT_DETECTED",
                {"pattern": pattern, "data_preview": data[:100]},
                "HIGH"
            )
            return False
    return True

def sanitize_input(data: str) -> str:
    """Sanitizar entrada de dados"""
    # Remover caracteres perigosos
    sanitized = re.sub(r'[<>"\']', '', data)
    return sanitized.strip()

def check_ip_reputation(ip: str) -> bool:
    """Verificar reputação do IP"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        
        # Verificar se é IP privado
        if ip_obj.is_private:
            return True
        
        # Verificar lista de IPs suspeitos
        if ip in SUSPICIOUS_IPS:
            security_manager.log_security_event(
                "SUSPICIOUS_IP_ACCESS",
                {"ip": ip},
                "HIGH"
            )
            return False
        
        return True
    except ValueError:
        return False

def advanced_rate_limit(limit_per_minute: int = 60, limit_per_hour: int = 1000):
    """Rate limiting avançado com múltiplas janelas de tempo"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = request.remote_addr
            current_time = datetime.now()
            
            # Verificar reputação do IP
            if not check_ip_reputation(ip_address):
                return jsonify({"message": "Acesso negado"}), 403
            
            # Chaves para diferentes janelas de tempo
            minute_key = f"rate_limit:minute:{ip_address}:{current_time.strftime('%Y%m%d%H%M')}"
            hour_key = f"rate_limit:hour:{ip_address}:{current_time.strftime('%Y%m%d%H')}"
            
            if REDIS_AVAILABLE:
                # Rate limiting por minuto
                minute_count = redis_client.incr(minute_key)
                if minute_count == 1:
                    redis_client.expire(minute_key, 60)
                
                # Rate limiting por hora
                hour_count = redis_client.incr(hour_key)
                if hour_count == 1:
                    redis_client.expire(hour_key, 3600)
                
                if minute_count > limit_per_minute or hour_count > limit_per_hour:
                    security_manager.log_security_event(
                        "RATE_LIMIT_EXCEEDED",
                        {"ip": ip_address, "minute_count": minute_count, "hour_count": hour_count},
                        "MEDIUM"
                    )
                    return jsonify({"message": "Limite de requisições excedido"}), 429
            else:
                # Fallback para cache em memória
                if ip_address not in memory_cache['rate_limits']:
                    memory_cache['rate_limits'][ip_address] = []
                
                # Limpar requisições antigas
                memory_cache['rate_limits'][ip_address] = [
                    t for t in memory_cache['rate_limits'][ip_address] 
                    if (current_time - t).total_seconds() < 60
                ]
                
                if len(memory_cache['rate_limits'][ip_address]) >= limit_per_minute:
                    return jsonify({"message": "Limite de requisições excedido"}), 429
                
                memory_cache['rate_limits'][ip_address].append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_auth(f):
    """Decorator para autenticação obrigatória"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Verificar header Authorization
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]

        if not token:
            security_manager.log_security_event(
                "UNAUTHORIZED_ACCESS_ATTEMPT",
                {"endpoint": request.endpoint, "method": request.method},
                "MEDIUM"
            )
            return jsonify({"message": "Token é necessário!"}), 401

        try:
            data = verify_token(token)
            if "error" in data:
                return jsonify({"message": data["error"]}), 401
            
            # Adicionar dados do usuário ao contexto da requisição
            g.current_user = data
            request.user = data
            
        except Exception as e:
            security_manager.log_security_event(
                "TOKEN_VERIFICATION_ERROR",
                {"error": str(e), "endpoint": request.endpoint},
                "HIGH"
            )
            return jsonify({"message": "Token inválido ou expirado"}), 401
        
        return f(*args, **kwargs)
    return decorated

def require_websocket_auth(f):
    """Decorator para autenticação WebSocket"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Implementar autenticação WebSocket
        # Token pode ser passado via query parameter ou header
        token = request.args.get('token')
        
        if not token:
            security_manager.log_security_event(
                "WEBSOCKET_UNAUTHORIZED_ACCESS",
                {"sid": request.sid if hasattr(request, 'sid') else 'unknown'},
                "MEDIUM"
            )
            disconnect()
            return
        
        data = verify_token(token)
        if "error" in data:
            security_manager.log_security_event(
                "WEBSOCKET_INVALID_TOKEN",
                {"error": data["error"], "sid": request.sid if hasattr(request, 'sid') else 'unknown'},
                "HIGH"
            )
            disconnect()
            return
        
        g.current_user = data
        return f(*args, **kwargs)
    return decorated

def add_security_headers(response):
    """Adicionar headers de segurança avançados"""
    # Headers básicos de segurança
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # HSTS (HTTP Strict Transport Security)
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    
    # CSP (Content Security Policy) mais restritivo
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "media-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "upgrade-insecure-requests"
    )
    response.headers['Content-Security-Policy'] = csp
    
    # Permissions Policy (Feature Policy)
    response.headers['Permissions-Policy'] = (
        "geolocation=(), "
        "microphone=(), "
        "camera=(), "
        "payment=(), "
        "usb=(), "
        "magnetometer=(), "
        "gyroscope=(), "
        "speaker=()"
    )
    
    # Cache control para dados sensíveis
    if request.endpoint and 'api' in request.endpoint:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    
    return response

def force_https(app):
    """Forçar HTTPS em produção"""
    @app.before_request
    def before_request():
        if not current_app.debug and not request.is_secure:
            if request.headers.get('X-Forwarded-Proto') != 'https':
                url = request.url.replace("http://", "https://", 1)
                security_manager.log_security_event(
                    "HTTP_TO_HTTPS_REDIRECT",
                    {"original_url": request.url, "redirect_url": url}
                )
                return redirect(url, code=301)

def validate_request_data():
    """Middleware para validar dados da requisição"""
    @current_app.before_request
    def validate_data():
        if request.is_json and request.json:
            for key, value in request.json.items():
                if isinstance(value, str):
                    if not validate_input(value):
                        security_manager.log_security_event(
                            "MALICIOUS_INPUT_BLOCKED",
                            {"key": key, "value_preview": value[:50]},
                            "HIGH"
                        )
                        return jsonify({"message": "Entrada inválida detectada"}), 400

def get_security_metrics() -> Dict[str, Any]:
    """Obter métricas de segurança"""
    return {
        "total_events": len(security_manager.security_events),
        "recent_events": security_manager.security_events[-10:],
        "active_sessions": len(security_manager.active_sessions),
        "redis_available": REDIS_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    }

