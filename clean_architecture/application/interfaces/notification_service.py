"""
Interface NotificationService - Camada de Aplicação
Define o contrato para serviços de notificação
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum

class NotificationType(Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBSOCKET = "websocket"
    SLACK = "slack"
    TELEGRAM = "telegram"

class NotificationPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class NotificationService(ABC):
    """Interface para serviços de notificação"""
    
    @abstractmethod
    async def send_welcome_email(self, email: str, username: str) -> bool:
        """Enviar email de boas-vindas"""
        pass
    
    @abstractmethod
    async def send_password_changed_notification(self, email: str, username: str) -> bool:
        """Enviar notificação de alteração de senha"""
        pass
    
    @abstractmethod
    async def send_password_reset_email(self, email: str, username: str, reset_token: str) -> bool:
        """Enviar email de reset de senha"""
        pass
    
    @abstractmethod
    async def send_password_reset_confirmation(self, email: str, username: str) -> bool:
        """Enviar confirmação de reset de senha"""
        pass
    
    @abstractmethod
    async def send_login_alert(self, email: str, username: str, ip_address: str, location: str) -> bool:
        """Enviar alerta de login"""
        pass
    
    @abstractmethod
    async def send_security_alert(self, email: str, username: str, alert_type: str, details: Dict[str, Any]) -> bool:
        """Enviar alerta de segurança"""
        pass
    
    @abstractmethod
    async def send_trade_notification(self, user_id: int, trade_data: Dict[str, Any], notification_types: List[NotificationType]) -> bool:
        """Enviar notificação de trade"""
        pass
    
    @abstractmethod
    async def send_portfolio_alert(self, user_id: int, alert_data: Dict[str, Any], priority: NotificationPriority) -> bool:
        """Enviar alerta de portfólio"""
        pass
    
    @abstractmethod
    async def send_market_alert(self, user_id: int, symbol: str, alert_data: Dict[str, Any]) -> bool:
        """Enviar alerta de mercado"""
        pass
    
    @abstractmethod
    async def send_system_notification(self, message: str, priority: NotificationPriority, target_users: Optional[List[int]] = None) -> bool:
        """Enviar notificação do sistema"""
        pass
    
    @abstractmethod
    async def send_custom_notification(
        self, 
        user_id: int, 
        title: str, 
        message: str, 
        notification_type: NotificationType,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Enviar notificação customizada"""
        pass
    
    @abstractmethod
    async def send_bulk_notification(
        self, 
        user_ids: List[int], 
        title: str, 
        message: str, 
        notification_type: NotificationType,
        priority: NotificationPriority = NotificationPriority.MEDIUM
    ) -> Dict[int, bool]:
        """Enviar notificação em massa"""
        pass
    
    @abstractmethod
    async def schedule_notification(
        self, 
        user_id: int, 
        title: str, 
        message: str, 
        notification_type: NotificationType,
        scheduled_time: str,  # ISO format
        priority: NotificationPriority = NotificationPriority.MEDIUM
    ) -> str:
        """Agendar notificação"""
        pass
    
    @abstractmethod
    async def cancel_scheduled_notification(self, notification_id: str) -> bool:
        """Cancelar notificação agendada"""
        pass
    
    @abstractmethod
    async def get_notification_preferences(self, user_id: int) -> Dict[str, Any]:
        """Obter preferências de notificação do usuário"""
        pass
    
    @abstractmethod
    async def update_notification_preferences(self, user_id: int, preferences: Dict[str, Any]) -> bool:
        """Atualizar preferências de notificação"""
        pass
    
    @abstractmethod
    async def get_notification_history(self, user_id: int, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Obter histórico de notificações"""
        pass
    
    @abstractmethod
    async def mark_notification_as_read(self, user_id: int, notification_id: str) -> bool:
        """Marcar notificação como lida"""
        pass
    
    @abstractmethod
    async def get_unread_notifications_count(self, user_id: int) -> int:
        """Obter contagem de notificações não lidas"""
        pass
    
    @abstractmethod
    async def send_websocket_notification(self, user_id: int, data: Dict[str, Any]) -> bool:
        """Enviar notificação via WebSocket"""
        pass
    
    @abstractmethod
    async def validate_email_address(self, email: str) -> bool:
        """Validar endereço de email"""
        pass
    
    @abstractmethod
    async def validate_phone_number(self, phone: str) -> bool:
        """Validar número de telefone"""
        pass
    
    @abstractmethod
    async def get_delivery_status(self, notification_id: str) -> Dict[str, Any]:
        """Obter status de entrega da notificação"""
        pass
    
    @abstractmethod
    async def retry_failed_notification(self, notification_id: str) -> bool:
        """Tentar reenviar notificação falhada"""
        pass

