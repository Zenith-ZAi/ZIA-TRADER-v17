"""
Interface TradeRepository - Camada de Domínio
Define o contrato para persistência de trades
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from datetime import datetime
from ..entities.trade import Trade, TradeStatus, TradeType

class TradeRepository(ABC):
    """Interface para repositório de trades"""
    
    @abstractmethod
    async def create(self, trade: Trade) -> Trade:
        """Criar novo trade"""
        pass
    
    @abstractmethod
    async def get_by_id(self, trade_id: int) -> Optional[Trade]:
        """Buscar trade por ID"""
        pass
    
    @abstractmethod
    async def update(self, trade: Trade) -> Trade:
        """Atualizar trade"""
        pass
    
    @abstractmethod
    async def delete(self, trade_id: int) -> bool:
        """Deletar trade"""
        pass
    
    @abstractmethod
    async def get_by_user_id(self, user_id: int, limit: int = 100, offset: int = 0) -> List[Trade]:
        """Buscar trades por usuário"""
        pass
    
    @abstractmethod
    async def get_by_status(self, status: TradeStatus, limit: int = 100, offset: int = 0) -> List[Trade]:
        """Buscar trades por status"""
        pass
    
    @abstractmethod
    async def get_pending_trades(self, user_id: Optional[int] = None) -> List[Trade]:
        """Buscar trades pendentes"""
        pass
    
    @abstractmethod
    async def get_by_symbol(self, symbol: str, user_id: Optional[int] = None, limit: int = 100) -> List[Trade]:
        """Buscar trades por símbolo"""
        pass
    
    @abstractmethod
    async def get_by_date_range(self, start_date: datetime, end_date: datetime, user_id: Optional[int] = None) -> List[Trade]:
        """Buscar trades por período"""
        pass
    
    @abstractmethod
    async def get_user_statistics(self, user_id: int) -> Dict[str, Any]:
        """Obter estatísticas de trades do usuário"""
        pass
    
    @abstractmethod
    async def get_symbol_statistics(self, symbol: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Obter estatísticas por símbolo"""
        pass
    
    @abstractmethod
    async def count_by_user(self, user_id: int) -> int:
        """Contar trades por usuário"""
        pass
    
    @abstractmethod
    async def count_by_status(self, status: TradeStatus) -> int:
        """Contar trades por status"""
        pass
    
    @abstractmethod
    async def get_recent_trades(self, user_id: int, limit: int = 10) -> List[Trade]:
        """Obter trades recentes do usuário"""
        pass
    
    @abstractmethod
    async def get_profitable_trades(self, user_id: int, limit: int = 100) -> List[Trade]:
        """Obter trades lucrativos"""
        pass
    
    @abstractmethod
    async def get_losing_trades(self, user_id: int, limit: int = 100) -> List[Trade]:
        """Obter trades com prejuízo"""
        pass
    
    @abstractmethod
    async def calculate_total_pnl(self, user_id: int) -> Dict[str, Any]:
        """Calcular P&L total do usuário"""
        pass
    
    @abstractmethod
    async def get_performance_metrics(self, user_id: int, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Obter métricas de performance"""
        pass

