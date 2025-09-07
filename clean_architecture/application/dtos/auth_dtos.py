"""
DTOs de Autenticação - Camada de Aplicação
Define os objetos de transferência de dados para autenticação
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field, validator
import re

class RegisterRequest(BaseModel):
    """DTO para requisição de registro"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = Field(None, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)
    
    @validator('username')
    def validate_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username deve conter apenas letras, números e underscore')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Senha deve ter pelo menos 8 caracteres')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Senha deve conter pelo menos uma letra maiúscula')
        if not re.search(r'[a-z]', v):
            raise ValueError('Senha deve conter pelo menos uma letra minúscula')
        if not re.search(r'\d', v):
            raise ValueError('Senha deve conter pelo menos um número')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Senha deve conter pelo menos um caractere especial')
        return v

class LoginRequest(BaseModel):
    """DTO para requisição de login"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=1)
    remember_me: bool = False
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    """DTO para requisição de refresh token"""
    refresh_token: str = Field(..., min_length=1)

class ChangePasswordRequest(BaseModel):
    """DTO para alteração de senha"""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Nova senha deve ter pelo menos 8 caracteres')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Nova senha deve conter pelo menos uma letra maiúscula')
        if not re.search(r'[a-z]', v):
            raise ValueError('Nova senha deve conter pelo menos uma letra minúscula')
        if not re.search(r'\d', v):
            raise ValueError('Nova senha deve conter pelo menos um número')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Nova senha deve conter pelo menos um caractere especial')
        return v

class PasswordResetRequest(BaseModel):
    """DTO para solicitação de reset de senha"""
    email: EmailStr

class PasswordResetConfirmRequest(BaseModel):
    """DTO para confirmação de reset de senha"""
    reset_token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    
    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Nova senha deve ter pelo menos 8 caracteres')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Nova senha deve conter pelo menos uma letra maiúscula')
        if not re.search(r'[a-z]', v):
            raise ValueError('Nova senha deve conter pelo menos uma letra minúscula')
        if not re.search(r'\d', v):
            raise ValueError('Nova senha deve conter pelo menos um número')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Nova senha deve conter pelo menos um caractere especial')
        return v

@dataclass
class TokenResponse:
    """DTO para resposta de token"""
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user_info: Optional[Dict[str, Any]] = None

@dataclass
class UserProfileResponse:
    """DTO para resposta de perfil do usuário"""
    id: int
    username: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    full_name: str
    created_at: str
    last_login: Optional[str]
    trading_enabled: bool
    risk_tolerance: str
    status: str

class UpdateProfileRequest(BaseModel):
    """DTO para atualização de perfil"""
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, max_length=50)
    last_name: Optional[str] = Field(None, max_length=50)
    
    @validator('first_name', 'last_name')
    def validate_names(cls, v):
        if v is not None and len(v.strip()) == 0:
            return None
        return v

class TradingSettingsRequest(BaseModel):
    """DTO para configurações de trading"""
    trading_enabled: bool
    risk_tolerance: str = Field(..., regex=r'^(low|medium|high)$')
    max_position_size: Optional[float] = Field(None, ge=0.01, le=1.0)
    max_portfolio_risk: Optional[float] = Field(None, ge=0.001, le=0.1)

@dataclass
class SecurityEventResponse:
    """DTO para eventos de segurança"""
    timestamp: str
    event_type: str
    details: Dict[str, Any]
    severity: str
    ip_address: str
    user_agent: str

@dataclass
class AuthValidationResponse:
    """DTO para resposta de validação de autenticação"""
    is_valid: bool
    user_id: Optional[int] = None
    username: Optional[str] = None
    permissions: Optional[list] = None
    expires_at: Optional[str] = None

