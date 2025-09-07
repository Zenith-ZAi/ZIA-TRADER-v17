from flask import Blueprint, jsonify, request, g
from src.models.user import User, db
from security_enhanced import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    create_refresh_token, 
    verify_token, 
    require_auth, 
    advanced_rate_limit,
    blacklist_token,
    validate_input,
    sanitize_input,
    security_manager
)
from pydantic import BaseModel, EmailStr, Field, ValidationError
from datetime import timedelta, datetime

user_bp = Blueprint("user", __name__)

# Modelos Pydantic para validação de input
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)

class UserLogin(BaseModel):
    username: str
    password: str

class TokenRefresh(BaseModel):
    refresh_token: str

class UserUpdate(BaseModel):
    email: EmailStr = None
    username: str = Field(None, min_length=3, max_length=50)

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

@user_bp.route("/register", methods=["POST"])
@advanced_rate_limit(limit_per_minute=5, limit_per_hour=20)
def register_user():
    try:
        # Validar e sanitizar dados de entrada
        raw_data = request.json
        if not raw_data:
            return jsonify({"message": "Dados não fornecidos"}), 400
        
        # Sanitizar dados
        for key, value in raw_data.items():
            if isinstance(value, str):
                if not validate_input(value):
                    return jsonify({"message": f"Entrada inválida detectada no campo {key}"}), 400
                raw_data[key] = sanitize_input(value)
        
        user_data = UserRegister(**raw_data)
    except ValidationError as e:
        security_manager.log_security_event(
            "INVALID_REGISTRATION_DATA",
            {"errors": e.errors(), "ip": request.remote_addr},
            "MEDIUM"
        )
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400
    except Exception as e:
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400

    # Verificar se usuário já existe
    if User.query.filter_by(username=user_data.username).first():
        security_manager.log_security_event(
            "DUPLICATE_USERNAME_ATTEMPT",
            {"username": user_data.username, "ip": request.remote_addr},
            "LOW"
        )
        return jsonify({"message": "Nome de usuário já existe"}), 409
    
    if User.query.filter_by(email=user_data.email).first():
        security_manager.log_security_event(
            "DUPLICATE_EMAIL_ATTEMPT",
            {"email": user_data.email, "ip": request.remote_addr},
            "LOW"
        )
        return jsonify({"message": "Email já registrado"}), 409

    # Criar usuário
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username, 
        email=user_data.email, 
        password_hash=hashed_password,
        created_at=datetime.utcnow()
    )
    
    try:
        db.session.add(new_user)
        db.session.commit()
        
        security_manager.log_security_event(
            "USER_REGISTERED",
            {"username": user_data.username, "email": user_data.email},
            "INFO"
        )
        
        return jsonify({"message": "Usuário registrado com sucesso"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Erro ao registrar usuário"}), 500

@user_bp.route("/login", methods=["POST"])
@advanced_rate_limit(limit_per_minute=10, limit_per_hour=100)
def login_user():
    try:
        # Validar e sanitizar dados
        raw_data = request.json
        if not raw_data:
            return jsonify({"message": "Dados não fornecidos"}), 400
        
        for key, value in raw_data.items():
            if isinstance(value, str):
                if not validate_input(value):
                    return jsonify({"message": f"Entrada inválida detectada no campo {key}"}), 400
                raw_data[key] = sanitize_input(value)
        
        user_data = UserLogin(**raw_data)
    except ValidationError as e:
        security_manager.log_security_event(
            "INVALID_LOGIN_DATA",
            {"errors": e.errors(), "ip": request.remote_addr},
            "MEDIUM"
        )
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400
    except Exception as e:
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400

    # Verificar credenciais
    user = User.query.filter_by(username=user_data.username).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        security_manager.log_security_event(
            "FAILED_LOGIN_ATTEMPT",
            {"username": user_data.username, "ip": request.remote_addr},
            "MEDIUM"
        )
        return jsonify({"message": "Credenciais inválidas"}), 401

    # Criar tokens
    access_token = create_access_token(data={"sub": user.username, "user_id": user.id})
    refresh_token = create_refresh_token(data={"sub": user.username, "user_id": user.id})

    # Atualizar último login
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    security_manager.log_security_event(
        "SUCCESSFUL_LOGIN",
        {"username": user.username, "user_id": user.id},
        "INFO"
    )

    return jsonify({
        "access_token": access_token, 
        "refresh_token": refresh_token, 
        "token_type": "bearer",
        "expires_in": 1800,  # 30 minutos
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        }
    }), 200

@user_bp.route("/refresh", methods=["POST"])
@advanced_rate_limit(limit_per_minute=20, limit_per_hour=200)
def refresh_token():
    try:
        raw_data = request.json
        if not raw_data:
            return jsonify({"message": "Dados não fornecidos"}), 400
        
        token_data = TokenRefresh(**raw_data)
    except ValidationError as e:
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400
    except Exception as e:
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400

    payload = verify_token(token_data.refresh_token)
    if "error" in payload:
        security_manager.log_security_event(
            "INVALID_REFRESH_TOKEN",
            {"error": payload["error"], "ip": request.remote_addr},
            "MEDIUM"
        )
        return jsonify({"message": payload["error"]}), 401

    username = payload.get("sub")
    user_id = payload.get("user_id")
    if not username:
        return jsonify({"message": "Token de refresh inválido"}), 401

    # Verificar se usuário ainda existe
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"message": "Usuário não encontrado"}), 401

    new_access_token = create_access_token(data={"sub": username, "user_id": user_id})
    
    security_manager.log_security_event(
        "TOKEN_REFRESHED",
        {"username": username, "user_id": user_id},
        "INFO"
    )
    
    return jsonify({
        "access_token": new_access_token, 
        "token_type": "bearer",
        "expires_in": 1800
    }), 200

@user_bp.route("/logout", methods=["POST"])
@require_auth
@advanced_rate_limit(limit_per_minute=30)
def logout_user():
    """Logout do usuário - invalidar tokens"""
    try:
        # Obter token do header
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            
            # Decodificar token para obter JTI
            payload = verify_token(token)
            if "error" not in payload:
                jti = payload.get('jti')
                exp = payload.get('exp')
                
                if jti and exp:
                    # Adicionar token à blacklist
                    expiry_date = datetime.fromtimestamp(exp)
                    blacklist_token(jti, expiry_date)
                    
                    security_manager.log_security_event(
                        "USER_LOGOUT",
                        {"username": payload.get("sub"), "jti": jti},
                        "INFO"
                    )
        
        return jsonify({"message": "Logout realizado com sucesso"}), 200
    except Exception as e:
        return jsonify({"message": "Erro no logout"}), 500

@user_bp.route("/profile", methods=["GET"])
@require_auth
@advanced_rate_limit(limit_per_minute=60)
def get_profile():
    """Obter perfil do usuário atual"""
    try:
        user_data = g.current_user
        user = User.query.filter_by(username=user_data.get("sub")).first()
        
        if not user:
            return jsonify({"message": "Usuário não encontrado"}), 404
        
        return jsonify({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None
        }), 200
    except Exception as e:
        return jsonify({"message": "Erro ao obter perfil"}), 500

@user_bp.route("/profile", methods=["PUT"])
@require_auth
@advanced_rate_limit(limit_per_minute=10)
def update_profile():
    """Atualizar perfil do usuário atual"""
    try:
        user_data = g.current_user
        user = User.query.filter_by(username=user_data.get("sub")).first()
        
        if not user:
            return jsonify({"message": "Usuário não encontrado"}), 404
        
        # Validar dados de entrada
        raw_data = request.json
        if not raw_data:
            return jsonify({"message": "Dados não fornecidos"}), 400
        
        # Sanitizar dados
        for key, value in raw_data.items():
            if isinstance(value, str):
                if not validate_input(value):
                    return jsonify({"message": f"Entrada inválida detectada no campo {key}"}), 400
                raw_data[key] = sanitize_input(value)
        
        update_data = UserUpdate(**raw_data)
        
        # Atualizar campos
        if update_data.email:
            # Verificar se email já existe
            existing_user = User.query.filter_by(email=update_data.email).first()
            if existing_user and existing_user.id != user.id:
                return jsonify({"message": "Email já está em uso"}), 409
            user.email = update_data.email
        
        if update_data.username:
            # Verificar se username já existe
            existing_user = User.query.filter_by(username=update_data.username).first()
            if existing_user and existing_user.id != user.id:
                return jsonify({"message": "Nome de usuário já está em uso"}), 409
            user.username = update_data.username
        
        db.session.commit()
        
        security_manager.log_security_event(
            "PROFILE_UPDATED",
            {"user_id": user.id, "username": user.username},
            "INFO"
        )
        
        return jsonify({
            "message": "Perfil atualizado com sucesso",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email
            }
        }), 200
        
    except ValidationError as e:
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Erro ao atualizar perfil"}), 500

@user_bp.route("/change-password", methods=["POST"])
@require_auth
@advanced_rate_limit(limit_per_minute=5)
def change_password():
    """Alterar senha do usuário"""
    try:
        user_data = g.current_user
        user = User.query.filter_by(username=user_data.get("sub")).first()
        
        if not user:
            return jsonify({"message": "Usuário não encontrado"}), 404
        
        # Validar dados
        raw_data = request.json
        if not raw_data:
            return jsonify({"message": "Dados não fornecidos"}), 400
        
        password_data = PasswordChange(**raw_data)
        
        # Verificar senha atual
        if not verify_password(password_data.current_password, user.password_hash):
            security_manager.log_security_event(
                "INVALID_PASSWORD_CHANGE_ATTEMPT",
                {"user_id": user.id, "username": user.username},
                "MEDIUM"
            )
            return jsonify({"message": "Senha atual incorreta"}), 401
        
        # Atualizar senha
        user.password_hash = get_password_hash(password_data.new_password)
        db.session.commit()
        
        security_manager.log_security_event(
            "PASSWORD_CHANGED",
            {"user_id": user.id, "username": user.username},
            "INFO"
        )
        
        return jsonify({"message": "Senha alterada com sucesso"}), 200
        
    except ValidationError as e:
        return jsonify({"message": "Erro de validação", "details": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Erro ao alterar senha"}), 500

# Rotas administrativas (apenas para usuários autorizados)
@user_bp.route("/users", methods=["GET"])
@require_auth
@advanced_rate_limit(limit_per_minute=30)
def get_users():
    """Listar usuários (admin)"""
    try:
        # TODO: Implementar verificação de permissões de admin
        users = User.query.all()
        return jsonify([{
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None
        } for user in users]), 200
    except Exception as e:
        return jsonify({"message": "Erro ao listar usuários"}), 500

@user_bp.route("/users/<int:user_id>", methods=["DELETE"])
@require_auth
@advanced_rate_limit(limit_per_minute=10)
def delete_user(user_id):
    """Deletar usuário (admin)"""
    try:
        # TODO: Implementar verificação de permissões de admin
        user = User.query.get_or_404(user_id)
        
        security_manager.log_security_event(
            "USER_DELETED",
            {"deleted_user_id": user_id, "deleted_username": user.username},
            "HIGH"
        )
        
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({"message": "Usuário deletado com sucesso"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Erro ao deletar usuário"}), 500

