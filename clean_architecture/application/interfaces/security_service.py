"""
Interface SecurityService - Camada de Aplicação
Define o contrato para serviços de segurança
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime

class SecurityService(ABC):
    """Interface para serviços de segurança"""
    
    @abstractmethod
    def hash_password(self, password: str) -> str:
        """Gerar hash da senha"""
        pass
    
    @abstractmethod
    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verificar senha contra hash"""
        pass
    
    @abstractmethod
    def validate_password_strength(self, password: str) -> bool:
        """Validar força da senha"""
        pass
    
    @abstractmethod
    def create_access_token(self, user_id: int, username: str, **kwargs) -> str:
        """Criar token de acesso"""
        pass
    
    @abstractmethod
    def create_refresh_token(self, user_id: int, username: str, **kwargs) -> str:
        """Criar token de refresh"""
        pass
    
    @abstractmethod
    def verify_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verificar token de acesso"""
        pass
    
    @abstractmethod
    def verify_refresh_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verificar token de refresh"""
        pass
    
    @abstractmethod
    def blacklist_token(self, jti: str, expiry: Optional[datetime] = None) -> None:
        """Adicionar token à blacklist"""
        pass
    
    @abstractmethod
    def is_token_blacklisted(self, jti: str) -> bool:
        """Verificar se token está na blacklist"""
        pass
    
    @abstractmethod
    def create_password_reset_token(self, user_id: int, email: str) -> str:
        """Criar token para reset de senha"""
        pass
    
    @abstractmethod
    def verify_password_reset_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verificar token de reset de senha"""
        pass
    
    @abstractmethod
    def encrypt_data(self, data: str) -> str:
        """Criptografar dados sensíveis"""
        pass
    
    @abstractmethod
    def decrypt_data(self, encrypted_data: str) -> str:
        """Descriptografar dados"""
        pass
    
    @abstractmethod
    def validate_input(self, data: str) -> bool:
        """Validar entrada contra padrões maliciosos"""
        pass
    
    @abstractmethod
    def sanitize_input(self, data: str) -> str:
        """Sanitizar entrada de dados"""
        pass
    
    @abstractmethod
    def check_rate_limit(self, identifier: str, limit: int, window: int) -> bool:
        """Verificar rate limiting"""
        pass
    
    @abstractmethod
    def log_security_event(self, event_type: str, details: Dict[str, Any], severity: str = "INFO") -> None:
        """Registrar evento de segurança"""
        pass
    
    @abstractmethod
    def get_security_metrics(self) -> Dict[str, Any]:
        """Obter métricas de segurança"""
        pass
    
    @abstractmethod
    def generate_secure_token(self, length: int = 32) -> str:
        """Gerar token seguro aleatório"""
        pass
    
    @abstractmethod
    def validate_ip_address(self, ip: str) -> bool:
        """Validar endereço IP"""
        pass
    
    @abstractmethod
    def check_ip_reputation(self, ip: str) -> bool:
        """Verificar reputação do IP"""
        pass
    
    @abstractmethod
    def detect_suspicious_activity(self, user_id: int, activity_data: Dict[str, Any]) -> bool:
        """Detectar atividade suspeita"""
        pass

