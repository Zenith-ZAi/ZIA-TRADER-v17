import pandas as pd
from typing import Dict, List, Optional, Any, Union
from abc import ABC, abstractmethod
from decimal import Decimal

class ExchangeAPI(ABC):
    """
    Interface abstrata para APIs de corretoras.
    Define os métodos que qualquer implementação de API de corretora deve ter.
    """

    @abstractmethod
    async def initialize(self):
        """Inicializa a conexão com a corretora."""
        pass

    @abstractmethod
    async def get_account_info(self) -> Dict[str, Any]:
        """Obtém informações da conta do usuário."""
        pass

    @abstractmethod
    async def get_market_data(
        self,
        symbol: str,
        timeframe: str = '1h',
        limit: int = 100
    ) -> pd.DataFrame:
        """Obtém dados de mercado (candlesticks) para um símbolo e timeframe."""
        pass

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """Obtém o preço atual de um símbolo."""
        pass

    @abstractmethod
    async def get_order_book(self, symbol: str, limit: int = 100) -> Dict[str, Any]:
        """Obtém o livro de ofertas (order book) para um símbolo."""
        pass

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Union[float, Decimal],
        price: Optional[Union[float, Decimal]] = None,
        time_in_force: Optional[str] = None,
        test: bool = False
    ) -> Dict[str, Any]:
        """Coloca uma ordem de compra ou venda."""
        pass

    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Obtém todas as ordens abertas ou ordens abertas para um símbolo específico."""
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancela uma ordem específica."""
        pass

    @abstractmethod
    async def get_trade_history(
        self,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Obtém o histórico de trades para um símbolo."""
        pass

    @abstractmethod
    async def get_exchange_info(self) -> Dict[str, Any]:
        """Obtém informações da corretora, como símbolos e filtros."""
        pass

    @abstractmethod
async def close(self):
        """Fecha a conexão com a corretora e limpa recursos."""
        pass


