import jwt
from datetime import datetime, timedelta
from typing import Optional
from cryptography.fernet import Fernet
from passlib.context import CryptContext
from functools import wraps
from flask import request, jsonify, current_app
from src.config import config

# Configuração do JWT
SECRET_KEY = config.security.jwt_secret_key
ALGORITHM = config.security.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = config.security.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = config.security.refresh_token_expire_days

# Configuração de criptografia de dados
DATA_ENCRYPTION_KEY = config.security.data_encryption_key.encode('utf-8')
fernet = Fernet(DATA_ENCRYPTION_KEY)

# Configuração de hash de senhas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dicionário para controle de rate limiting (em memória, para produção usar Redis)
rate_limit_tracker = {}

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return {"error": "Token expirado"}
    except jwt.InvalidTokenError:
        return {"error": "Token inválido"}

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def encrypt_data(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    return fernet.decrypt(encrypted_data.encode()).decode()

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]

        if not token:
            return jsonify({"message": "Token é necessário!"}), 401

        try:
            data = verify_token(token)
            if "error" in data:
                return jsonify({"message": data["error"]}), 401
            request.user = data # Adiciona os dados do usuário ao objeto request
        except Exception as e:
            return jsonify({"message": "Token inválido ou expirado", "error": str(e)}), 401
        return f(*args, **kwargs)
    return decorated

def rate_limit(limit_per_minute: int = config.security.api_rate_limit_per_minute):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip_address = request.remote_addr
            current_time = datetime.now()

            if ip_address not in rate_limit_tracker:
                rate_limit_tracker[ip_address] = []
            
            # Remover requisições antigas (fora da janela de 1 minuto)
            rate_limit_tracker[ip_address] = [t for t in rate_limit_tracker[ip_address] if (current_time - t).total_seconds() < 60]

            if len(rate_limit_tracker[ip_address]) >= limit_per_minute:
                return jsonify({"message": "Limite de requisições excedido. Tente novamente mais tarde."}), 429
            
            rate_limit_tracker[ip_address].append(current_time)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Middleware para forçar HTTPS (apenas para ambiente de produção)
def force_https(app):
    @app.before_request
    def before_request():
        if not current_app.debug and not request.is_secure:
            url = request.url.replace("http://", "https://", 1)
            code = 301
            return redirect(url, code=code)

# Headers de segurança
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' ws:"
    return response



