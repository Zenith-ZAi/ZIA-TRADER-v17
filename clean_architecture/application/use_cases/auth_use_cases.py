"""
Casos de Uso de Autenticação - Camada de Aplicação
Implementa a lógica de negócio para autenticação
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from ...domain.entities.user import User, UserStatus
from ...domain.repositories.user_repository import UserRepository
from ..dtos.auth_dtos import LoginRequest, RegisterRequest, TokenResponse, RefreshTokenRequest
from ..interfaces.security_service import SecurityService
from ..interfaces.notification_service import NotificationService

class AuthenticationError(Exception):
    """Exceção para erros de autenticação"""
    pass

class RegistrationError(Exception):
    """Exceção para erros de registro"""
    pass

@dataclass
class AuthUseCase:
    """Casos de uso de autenticação"""
    
    user_repository: UserRepository
    security_service: SecurityService
    notification_service: NotificationService
    
    async def register_user(self, request: RegisterRequest) -> TokenResponse:
        """Registrar novo usuário"""
        
        # Verificar se usuário já existe
        if await self.user_repository.exists_username(request.username):
            raise RegistrationError("Nome de usuário já existe")
        
        if await self.user_repository.exists_email(request.email):
            raise RegistrationError("Email já está registrado")
        
        # Validar força da senha
        if not self.security_service.validate_password_strength(request.password):
            raise RegistrationError("Senha não atende aos critérios de segurança")
        
        # Criar hash da senha
        password_hash = self.security_service.hash_password(request.password)
        
        # Criar usuário
        user = User(
            id=None,
            username=request.username,
            email=request.email,
            password_hash=password_hash,
            created_at=datetime.utcnow(),
            status=UserStatus.ACTIVE,
            first_name=request.first_name,
            last_name=request.last_name
        )
        
        # Salvar no repositório
        created_user = await self.user_repository.create(user)
        
        # Gerar tokens
        access_token = self.security_service.create_access_token(
            user_id=created_user.id,
            username=created_user.username
        )
        
        refresh_token = self.security_service.create_refresh_token(
            user_id=created_user.id,
            username=created_user.username
        )
        
        # Enviar notificação de boas-vindas
        await self.notification_service.send_welcome_email(created_user.email, created_user.username)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=1800,  # 30 minutos
            user_info={
                "id": created_user.id,
                "username": created_user.username,
                "email": created_user.email
            }
        )
    
    async def login_user(self, request: LoginRequest) -> TokenResponse:
        """Fazer login do usuário"""
        
        # Buscar usuário
        user = await self.user_repository.get_by_username(request.username)
        if not user:
            raise AuthenticationError("Credenciais inválidas")
        
        # Verificar se conta está bloqueada
        if user.is_locked():
            raise AuthenticationError("Conta temporariamente bloqueada")
        
        # Verificar se conta está ativa
        if not user.is_active():
            raise AuthenticationError("Conta inativa")
        
        # Verificar senha
        if not self.security_service.verify_password(request.password, user.password_hash):
            # Incrementar tentativas falhadas
            user.increment_failed_login()
            await self.user_repository.update(user)
            
            # Log de tentativa de login falhada
            await self.security_service.log_security_event(
                "FAILED_LOGIN_ATTEMPT",
                {"username": request.username, "ip": request.ip_address},
                "MEDIUM"
            )
            
            raise AuthenticationError("Credenciais inválidas")
        
        # Login bem-sucedido
        user.update_last_login()
        await self.user_repository.update(user)
        
        # Gerar tokens
        access_token = self.security_service.create_access_token(
            user_id=user.id,
            username=user.username
        )
        
        refresh_token = self.security_service.create_refresh_token(
            user_id=user.id,
            username=user.username
        )
        
        # Log de login bem-sucedido
        await self.security_service.log_security_event(
            "SUCCESSFUL_LOGIN",
            {"username": user.username, "user_id": user.id, "ip": request.ip_address},
            "INFO"
        )
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=1800,
            user_info={
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "trading_enabled": user.trading_enabled
            }
        )
    
    async def refresh_token(self, request: RefreshTokenRequest) -> TokenResponse:
        """Renovar token de acesso"""
        
        # Verificar refresh token
        payload = self.security_service.verify_refresh_token(request.refresh_token)
        if not payload:
            raise AuthenticationError("Refresh token inválido")
        
        user_id = payload.get("user_id")
        username = payload.get("username")
        
        if not user_id or not username:
            raise AuthenticationError("Refresh token inválido")
        
        # Verificar se usuário ainda existe e está ativo
        user = await self.user_repository.get_by_id(user_id)
        if not user or not user.is_active():
            raise AuthenticationError("Usuário não encontrado ou inativo")
        
        # Gerar novo access token
        access_token = self.security_service.create_access_token(
            user_id=user.id,
            username=user.username
        )
        
        # Log de token renovado
        await self.security_service.log_security_event(
            "TOKEN_REFRESHED",
            {"username": username, "user_id": user_id},
            "INFO"
        )
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=request.refresh_token,  # Manter o mesmo refresh token
            token_type="bearer",
            expires_in=1800
        )
    
    async def logout_user(self, access_token: str) -> bool:
        """Fazer logout do usuário"""
        
        # Verificar token
        payload = self.security_service.verify_access_token(access_token)
        if not payload:
            return False
        
        # Adicionar token à blacklist
        jti = payload.get("jti")
        exp = payload.get("exp")
        
        if jti and exp:
            expiry_date = datetime.fromtimestamp(exp)
            self.security_service.blacklist_token(jti, expiry_date)
            
            # Log de logout
            await self.security_service.log_security_event(
                "USER_LOGOUT",
                {"username": payload.get("username"), "jti": jti},
                "INFO"
            )
        
        return True
    
    async def validate_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Validar token de acesso"""
        
        payload = self.security_service.verify_access_token(access_token)
        if not payload:
            return None
        
        user_id = payload.get("user_id")
        if not user_id:
            return None
        
        # Verificar se usuário ainda está ativo
        user = await self.user_repository.get_by_id(user_id)
        if not user or not user.is_active():
            return None
        
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "trading_enabled": user.trading_enabled,
            "risk_tolerance": user.risk_tolerance.value
        }
    
    async def change_password(self, user_id: int, current_password: str, new_password: str) -> bool:
        """Alterar senha do usuário"""
        
        # Buscar usuário
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            raise AuthenticationError("Usuário não encontrado")
        
        # Verificar senha atual
        if not self.security_service.verify_password(current_password, user.password_hash):
            raise AuthenticationError("Senha atual incorreta")
        
        # Validar nova senha
        if not self.security_service.validate_password_strength(new_password):
            raise AuthenticationError("Nova senha não atende aos critérios de segurança")
        
        # Atualizar senha
        user.password_hash = self.security_service.hash_password(new_password)
        await self.user_repository.update(user)
        
        # Log de alteração de senha
        await self.security_service.log_security_event(
            "PASSWORD_CHANGED",
            {"user_id": user.id, "username": user.username},
            "INFO"
        )
        
        # Enviar notificação por email
        await self.notification_service.send_password_changed_notification(user.email, user.username)
        
        return True
    
    async def request_password_reset(self, email: str) -> bool:
        """Solicitar reset de senha"""
        
        # Buscar usuário por email
        user = await self.user_repository.get_by_email(email)
        if not user:
            # Por segurança, não revelar se o email existe
            return True
        
        # Gerar token de reset
        reset_token = self.security_service.create_password_reset_token(user.id, user.email)
        
        # Enviar email com token
        await self.notification_service.send_password_reset_email(user.email, user.username, reset_token)
        
        # Log de solicitação de reset
        await self.security_service.log_security_event(
            "PASSWORD_RESET_REQUESTED",
            {"user_id": user.id, "email": user.email},
            "INFO"
        )
        
        return True
    
    async def reset_password(self, reset_token: str, new_password: str) -> bool:
        """Resetar senha com token"""
        
        # Verificar token de reset
        payload = self.security_service.verify_password_reset_token(reset_token)
        if not payload:
            raise AuthenticationError("Token de reset inválido ou expirado")
        
        user_id = payload.get("user_id")
        if not user_id:
            raise AuthenticationError("Token de reset inválido")
        
        # Buscar usuário
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            raise AuthenticationError("Usuário não encontrado")
        
        # Validar nova senha
        if not self.security_service.validate_password_strength(new_password):
            raise AuthenticationError("Nova senha não atende aos critérios de segurança")
        
        # Atualizar senha
        user.password_hash = self.security_service.hash_password(new_password)
        user.reset_failed_login()  # Resetar tentativas falhadas
        await self.user_repository.update(user)
        
        # Log de reset de senha
        await self.security_service.log_security_event(
            "PASSWORD_RESET_COMPLETED",
            {"user_id": user.id, "username": user.username},
            "INFO"
        )
        
        # Enviar confirmação por email
        await self.notification_service.send_password_reset_confirmation(user.email, user.username)
        
        return True

