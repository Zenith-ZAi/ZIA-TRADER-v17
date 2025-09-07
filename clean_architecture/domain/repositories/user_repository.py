"""
Interface UserRepository - Camada de Domínio
Define o contrato para persistência de usuários
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from ..entities.user import User

class UserRepository(ABC):
    """Interface para repositório de usuários"""
    
    @abstractmethod
    async def create(self, user: User) -> User:
        """Criar novo usuário"""
        pass
    
    @abstractmethod
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Buscar usuário por ID"""
        pass
    
    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[User]:
        """Buscar usuário por username"""
        pass
    
    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """Buscar usuário por email"""
        pass
    
    @abstractmethod
    async def update(self, user: User) -> User:
        """Atualizar usuário"""
        pass
    
    @abstractmethod
    async def delete(self, user_id: int) -> bool:
        """Deletar usuário"""
        pass
    
    @abstractmethod
    async def list_all(self, limit: int = 100, offset: int = 0) -> List[User]:
        """Listar todos os usuários"""
        pass
    
    @abstractmethod
    async def list_active(self, limit: int = 100, offset: int = 0) -> List[User]:
        """Listar usuários ativos"""
        pass
    
    @abstractmethod
    async def count_total(self) -> int:
        """Contar total de usuários"""
        pass
    
    @abstractmethod
    async def exists_username(self, username: str) -> bool:
        """Verificar se username existe"""
        pass
    
    @abstractmethod
    async def exists_email(self, email: str) -> bool:
        """Verificar se email existe"""
        pass
    
    @abstractmethod
    async def get_locked_users(self) -> List[User]:
        """Obter usuários bloqueados"""
        pass
    
    @abstractmethod
    async def unlock_expired_users(self) -> int:
        """Desbloquear usuários com bloqueio expirado"""
        pass

