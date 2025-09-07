"""
Gerenciador WebSocket para RoboTrader 2.0
Implementa comunicação em tempo real com autenticação e segurança
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask import request, g
from security_enhanced import verify_token, security_manager, require_websocket_auth
from dataclasses import dataclass, asdict
from enum import Enum

# Configuração do logger
websocket_logger = logging.getLogger('websocket')
websocket_logger.setLevel(logging.INFO)
handler = logging.FileHandler('logs/websocket.log')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
websocket_logger.addHandler(handler)

class MessageType(Enum):
    """Tipos de mensagens WebSocket"""
    MARKET_DATA = "market_data"
    TRADE_SIGNAL = "trade_signal"
    PORTFOLIO_UPDATE = "portfolio_update"
    SYSTEM_STATUS = "system_status"
    ALERT = "alert"
    ERROR = "error"
    HEARTBEAT = "heartbeat"
    USER_ACTION = "user_action"
    NOTIFICATION = "notification"

class AlertLevel(Enum):
    """Níveis de alerta"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class WebSocketMessage:
    """Estrutura padrão de mensagem WebSocket"""
    type: MessageType
    data: Dict[str, Any]
    timestamp: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type.value,
            'data': self.data,
            'timestamp': self.timestamp,
            'user_id': self.user_id,
            'session_id': self.session_id
        }

class WebSocketManager:
    """Gerenciador central de WebSocket"""
    
    def __init__(self, socketio: SocketIO):
        self.socketio = socketio
        self.connected_users: Dict[str, Set[str]] = {}  # user_id -> set of session_ids
        self.user_sessions: Dict[str, str] = {}  # session_id -> user_id
        self.user_rooms: Dict[str, Set[str]] = {}  # user_id -> set of rooms
        self.active_subscriptions: Dict[str, Set[str]] = {}  # session_id -> set of subscriptions
        
        # Registrar event handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Registrar handlers de eventos WebSocket"""
        
        @self.socketio.on('connect')
        def handle_connect(auth):
            """Handler para conexão WebSocket"""
            try:
                # Verificar autenticação
                token = request.args.get('token') or (auth.get('token') if auth else None)
                
                if not token:
                    websocket_logger.warning(f"Conexão WebSocket sem token: {request.sid}")
                    disconnect()
                    return False
                
                # Verificar token
                token_data = verify_token(token)
                if "error" in token_data:
                    websocket_logger.warning(f"Token inválido na conexão WebSocket: {token_data['error']}")
                    disconnect()
                    return False
                
                user_id = token_data.get('sub')
                session_id = request.sid
                
                # Registrar usuário conectado
                if user_id not in self.connected_users:
                    self.connected_users[user_id] = set()
                self.connected_users[user_id].add(session_id)
                self.user_sessions[session_id] = user_id
                
                # Adicionar à sala do usuário
                join_room(f"user_{user_id}")
                
                # Log da conexão
                security_manager.log_security_event(
                    "WEBSOCKET_CONNECTION",
                    {"user_id": user_id, "session_id": session_id}
                )
                
                websocket_logger.info(f"Usuário {user_id} conectado via WebSocket: {session_id}")
                
                # Enviar confirmação de conexão
                self.send_to_user(user_id, WebSocketMessage(
                    type=MessageType.SYSTEM_STATUS,
                    data={"status": "connected", "message": "Conectado com sucesso"},
                    timestamp=datetime.utcnow().isoformat(),
                    user_id=user_id,
                    session_id=session_id
                ))
                
                return True
                
            except Exception as e:
                websocket_logger.error(f"Erro na conexão WebSocket: {str(e)}")
                disconnect()
                return False
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handler para desconexão WebSocket"""
            session_id = request.sid
            user_id = self.user_sessions.get(session_id)
            
            if user_id:
                # Remover da lista de usuários conectados
                if user_id in self.connected_users:
                    self.connected_users[user_id].discard(session_id)
                    if not self.connected_users[user_id]:
                        del self.connected_users[user_id]
                
                # Remover das salas
                if user_id in self.user_rooms:
                    for room in self.user_rooms[user_id]:
                        leave_room(room)
                    del self.user_rooms[user_id]
                
                # Limpar sessão
                del self.user_sessions[session_id]
                
                # Limpar subscrições
                if session_id in self.active_subscriptions:
                    del self.active_subscriptions[session_id]
                
                # Log da desconexão
                security_manager.log_security_event(
                    "WEBSOCKET_DISCONNECTION",
                    {"user_id": user_id, "session_id": session_id}
                )
                
                websocket_logger.info(f"Usuário {user_id} desconectado: {session_id}")
        
        @self.socketio.on('subscribe')
        def handle_subscribe(data):
            """Handler para subscrições"""
            session_id = request.sid
            user_id = self.user_sessions.get(session_id)
            
            if not user_id:
                emit('error', {'message': 'Usuário não autenticado'})
                return
            
            try:
                subscription_type = data.get('type')
                subscription_params = data.get('params', {})
                
                # Validar tipo de subscrição
                valid_subscriptions = [
                    'market_data',
                    'trade_signals',
                    'portfolio_updates',
                    'system_alerts',
                    'notifications'
                ]
                
                if subscription_type not in valid_subscriptions:
                    emit('error', {'message': 'Tipo de subscrição inválido'})
                    return
                
                # Adicionar subscrição
                if session_id not in self.active_subscriptions:
                    self.active_subscriptions[session_id] = set()
                self.active_subscriptions[session_id].add(subscription_type)
                
                # Adicionar à sala específica
                room_name = f"{subscription_type}_{user_id}"
                join_room(room_name)
                
                if user_id not in self.user_rooms:
                    self.user_rooms[user_id] = set()
                self.user_rooms[user_id].add(room_name)
                
                websocket_logger.info(f"Usuário {user_id} subscrito em {subscription_type}")
                
                emit('subscription_confirmed', {
                    'type': subscription_type,
                    'status': 'active',
                    'params': subscription_params
                })
                
            except Exception as e:
                websocket_logger.error(f"Erro na subscrição: {str(e)}")
                emit('error', {'message': 'Erro ao processar subscrição'})
        
        @self.socketio.on('unsubscribe')
        def handle_unsubscribe(data):
            """Handler para cancelar subscrições"""
            session_id = request.sid
            user_id = self.user_sessions.get(session_id)
            
            if not user_id:
                emit('error', {'message': 'Usuário não autenticado'})
                return
            
            try:
                subscription_type = data.get('type')
                
                # Remover subscrição
                if session_id in self.active_subscriptions:
                    self.active_subscriptions[session_id].discard(subscription_type)
                
                # Sair da sala
                room_name = f"{subscription_type}_{user_id}"
                leave_room(room_name)
                
                if user_id in self.user_rooms:
                    self.user_rooms[user_id].discard(room_name)
                
                websocket_logger.info(f"Usuário {user_id} cancelou subscrição em {subscription_type}")
                
                emit('unsubscription_confirmed', {
                    'type': subscription_type,
                    'status': 'inactive'
                })
                
            except Exception as e:
                websocket_logger.error(f"Erro ao cancelar subscrição: {str(e)}")
                emit('error', {'message': 'Erro ao cancelar subscrição'})
        
        @self.socketio.on('heartbeat')
        def handle_heartbeat():
            """Handler para heartbeat"""
            session_id = request.sid
            user_id = self.user_sessions.get(session_id)
            
            if user_id:
                emit('heartbeat_response', {
                    'timestamp': datetime.utcnow().isoformat(),
                    'status': 'alive'
                })
    
    def send_to_user(self, user_id: str, message: WebSocketMessage):
        """Enviar mensagem para um usuário específico"""
        try:
            room_name = f"user_{user_id}"
            self.socketio.emit(
                message.type.value,
                message.to_dict(),
                room=room_name
            )
            websocket_logger.debug(f"Mensagem enviada para usuário {user_id}: {message.type.value}")
        except Exception as e:
            websocket_logger.error(f"Erro ao enviar mensagem para usuário {user_id}: {str(e)}")
    
    def send_to_subscribers(self, subscription_type: str, message: WebSocketMessage):
        """Enviar mensagem para todos os subscritores de um tipo"""
        try:
            for session_id, subscriptions in self.active_subscriptions.items():
                if subscription_type in subscriptions:
                    user_id = self.user_sessions.get(session_id)
                    if user_id:
                        room_name = f"{subscription_type}_{user_id}"
                        self.socketio.emit(
                            message.type.value,
                            message.to_dict(),
                            room=room_name
                        )
            
            websocket_logger.debug(f"Mensagem enviada para subscritores de {subscription_type}")
        except Exception as e:
            websocket_logger.error(f"Erro ao enviar mensagem para subscritores: {str(e)}")
    
    def broadcast_alert(self, level: AlertLevel, title: str, message: str, data: Optional[Dict] = None):
        """Broadcast de alerta para todos os usuários conectados"""
        alert_message = WebSocketMessage(
            type=MessageType.ALERT,
            data={
                "level": level.value,
                "title": title,
                "message": message,
                "data": data or {}
            },
            timestamp=datetime.utcnow().isoformat()
        )
        
        try:
            self.socketio.emit('alert', alert_message.to_dict(), broadcast=True)
            websocket_logger.info(f"Alerta broadcast: {level.value} - {title}")
        except Exception as e:
            websocket_logger.error(f"Erro ao enviar alerta broadcast: {str(e)}")
    
    def send_market_data(self, symbol: str, data: Dict[str, Any]):
        """Enviar dados de mercado para subscritores"""
        message = WebSocketMessage(
            type=MessageType.MARKET_DATA,
            data={
                "symbol": symbol,
                "price": data.get("price"),
                "volume": data.get("volume"),
                "change": data.get("change"),
                "timestamp": data.get("timestamp", datetime.utcnow().isoformat())
            },
            timestamp=datetime.utcnow().isoformat()
        )
        
        self.send_to_subscribers("market_data", message)
    
    def send_trade_signal(self, user_id: str, signal_data: Dict[str, Any]):
        """Enviar sinal de trade para usuário"""
        message = WebSocketMessage(
            type=MessageType.TRADE_SIGNAL,
            data=signal_data,
            timestamp=datetime.utcnow().isoformat(),
            user_id=user_id
        )
        
        self.send_to_user(user_id, message)
    
    def send_portfolio_update(self, user_id: str, portfolio_data: Dict[str, Any]):
        """Enviar atualização de portfólio"""
        message = WebSocketMessage(
            type=MessageType.PORTFOLIO_UPDATE,
            data=portfolio_data,
            timestamp=datetime.utcnow().isoformat(),
            user_id=user_id
        )
        
        self.send_to_user(user_id, message)
    
    def send_system_status(self, status_data: Dict[str, Any]):
        """Enviar status do sistema para todos"""
        message = WebSocketMessage(
            type=MessageType.SYSTEM_STATUS,
            data=status_data,
            timestamp=datetime.utcnow().isoformat()
        )
        
        try:
            self.socketio.emit('system_status', message.to_dict(), broadcast=True)
        except Exception as e:
            websocket_logger.error(f"Erro ao enviar status do sistema: {str(e)}")
    
    def get_connected_users(self) -> List[str]:
        """Obter lista de usuários conectados"""
        return list(self.connected_users.keys())
    
    def get_user_sessions(self, user_id: str) -> List[str]:
        """Obter sessões de um usuário"""
        return list(self.connected_users.get(user_id, set()))
    
    def is_user_connected(self, user_id: str) -> bool:
        """Verificar se usuário está conectado"""
        return user_id in self.connected_users and len(self.connected_users[user_id]) > 0
    
    def disconnect_user(self, user_id: str, reason: str = "Desconectado pelo sistema"):
        """Desconectar usuário específico"""
        if user_id in self.connected_users:
            sessions = list(self.connected_users[user_id])
            for session_id in sessions:
                self.socketio.emit('disconnect_notice', {
                    'reason': reason,
                    'timestamp': datetime.utcnow().isoformat()
                }, room=session_id)
                self.socketio.disconnect(session_id)
            
            websocket_logger.info(f"Usuário {user_id} desconectado: {reason}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obter estatísticas do WebSocket"""
        return {
            "connected_users": len(self.connected_users),
            "total_sessions": len(self.user_sessions),
            "active_subscriptions": sum(len(subs) for subs in self.active_subscriptions.values()),
            "rooms": sum(len(rooms) for rooms in self.user_rooms.values()),
            "timestamp": datetime.utcnow().isoformat()
        }

# Instância global do gerenciador WebSocket
websocket_manager = None

def initialize_websocket_manager(socketio: SocketIO) -> WebSocketManager:
    """Inicializar gerenciador WebSocket"""
    global websocket_manager
    websocket_manager = WebSocketManager(socketio)
    return websocket_manager

def get_websocket_manager() -> Optional[WebSocketManager]:
    """Obter instância do gerenciador WebSocket"""
    return websocket_manager

