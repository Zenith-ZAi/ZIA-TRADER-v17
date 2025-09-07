"""
Entidade User - Camada de Domínio
Representa um usuário do sistema RoboTrader
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

class RiskTolerance(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class UserStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"

@dataclass
class User:
    """Entidade User do domínio"""
    
    id: Optional[int]
    username: str
    email: str
    password_hash: str
    
    # Campos de auditoria
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    
    # Campos de segurança
    status: UserStatus = UserStatus.ACTIVE
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    
    # Campos de perfil
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    
    # Configurações de trading
    trading_enabled: bool = False
    risk_tolerance: RiskTolerance = RiskTolerance.MEDIUM
    
    def __post_init__(self):
        """Validações após inicialização"""
        if not self.username or len(self.username) < 3:
            raise ValueError("Username deve ter pelo menos 3 caracteres")
        
        if not self.email or "@" not in self.email:
            raise ValueError("Email inválido")
        
        if not self.password_hash:
            raise ValueError("Password hash é obrigatório")
    
    def is_locked(self) -> bool:
        """Verificar se a conta está bloqueada"""
        if self.status == UserStatus.LOCKED:
            return True
        
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        
        return False
    
    def is_active(self) -> bool:
        """Verificar se a conta está ativa"""
        return self.status == UserStatus.ACTIVE and not self.is_locked()
    
    def can_trade(self) -> bool:
        """Verificar se o usuário pode fazer trades"""
        return self.is_active() and self.trading_enabled
    
    def get_full_name(self) -> str:
        """Obter nome completo"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        else:
            return self.username
    
    def increment_failed_login(self) -> None:
        """Incrementar tentativas de login falhadas"""
        self.failed_login_attempts += 1
        
        # Bloquear conta após 5 tentativas falhadas
        if self.failed_login_attempts >= 5:
            from datetime import timedelta
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)
            self.status = UserStatus.LOCKED
    
    def reset_failed_login(self) -> None:
        """Resetar tentativas de login falhadas"""
        self.failed_login_attempts = 0
        self.locked_until = None
        if self.status == UserStatus.LOCKED:
            self.status = UserStatus.ACTIVE
    
    def update_last_login(self) -> None:
        """Atualizar último login"""
        self.last_login = datetime.utcnow()
        self.reset_failed_login()
    
    def enable_trading(self) -> None:
        """Habilitar trading para o usuário"""
        if not self.is_active():
            raise ValueError("Usuário deve estar ativo para habilitar trading")
        self.trading_enabled = True
    
    def disable_trading(self) -> None:
        """Desabilitar trading para o usuário"""
        self.trading_enabled = False
    
    def set_risk_tolerance(self, risk_tolerance: RiskTolerance) -> None:
        """Definir tolerância ao risco"""
        self.risk_tolerance = risk_tolerance
    
    def suspend(self) -> None:
        """Suspender usuário"""
        self.status = UserStatus.SUSPENDED
        self.trading_enabled = False
    
    def activate(self) -> None:
        """Ativar usuário"""
        self.status = UserStatus.ACTIVE
        self.reset_failed_login()
    
    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Converter para dicionário"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'status': self.status.value,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'trading_enabled': self.trading_enabled,
            'risk_tolerance': self.risk_tolerance.value,
            'full_name': self.get_full_name()
        }
        
        if include_sensitive:
            data.update({
                'failed_login_attempts': self.failed_login_attempts,
                'locked_until': self.locked_until.isoformat() if self.locked_until else None,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None
            })
        
        return data

