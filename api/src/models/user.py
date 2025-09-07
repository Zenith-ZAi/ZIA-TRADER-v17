from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Campos de auditoria
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Campos de segurança
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    
    # Campos de perfil
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    
    # Configurações de trading (opcional)
    trading_enabled = db.Column(db.Boolean, default=False)
    risk_tolerance = db.Column(db.String(20), default='medium')  # low, medium, high
    
    def __repr__(self):
        return f'<User {self.username}>'
    
    def to_dict(self, include_sensitive=False):
        """Converter para dicionário, opcionalmente incluindo dados sensíveis"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'is_active': self.is_active,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'trading_enabled': self.trading_enabled,
            'risk_tolerance': self.risk_tolerance
        }
        
        if include_sensitive:
            data.update({
                'failed_login_attempts': self.failed_login_attempts,
                'locked_until': self.locked_until.isoformat() if self.locked_until else None,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None
            })
        
        return data
    
    def is_locked(self):
        """Verificar se a conta está bloqueada"""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False
    
    def increment_failed_login(self):
        """Incrementar tentativas de login falhadas"""
        self.failed_login_attempts += 1
        
        # Bloquear conta após 5 tentativas falhadas por 30 minutos
        if self.failed_login_attempts >= 5:
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)
    
    def reset_failed_login(self):
        """Resetar tentativas de login falhadas"""
        self.failed_login_attempts = 0
        self.locked_until = None
    
    def get_full_name(self):
        """Obter nome completo"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        else:
            return self.username


