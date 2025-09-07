"""
Entidade Portfolio - Camada de Domínio
Representa o portfólio de investimentos de um usuário
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from decimal import Decimal
from enum import Enum

class PortfolioStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

@dataclass
class Position:
    """Representa uma posição no portfólio"""
    symbol: str
    quantity: Decimal
    average_price: Decimal
    current_price: Decimal = Decimal('0')
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def get_market_value(self) -> Decimal:
        """Obter valor de mercado da posição"""
        return self.quantity * self.current_price
    
    def get_cost_basis(self) -> Decimal:
        """Obter custo base da posição"""
        return self.quantity * self.average_price
    
    def get_unrealized_pnl(self) -> Decimal:
        """Obter P&L não realizado"""
        return self.get_market_value() - self.get_cost_basis()
    
    def get_unrealized_pnl_percentage(self) -> float:
        """Obter P&L não realizado em percentual"""
        cost_basis = self.get_cost_basis()
        if cost_basis == 0:
            return 0.0
        return float(self.get_unrealized_pnl() / cost_basis * 100)
    
    def update_price(self, new_price: Decimal) -> None:
        """Atualizar preço atual"""
        self.current_price = new_price
        self.last_updated = datetime.utcnow()
    
    def add_quantity(self, quantity: Decimal, price: Decimal) -> None:
        """Adicionar quantidade à posição (recalcula preço médio)"""
        if quantity <= 0:
            raise ValueError("Quantidade deve ser positiva")
        
        total_cost = self.get_cost_basis() + (quantity * price)
        total_quantity = self.quantity + quantity
        
        self.average_price = total_cost / total_quantity
        self.quantity = total_quantity
        self.last_updated = datetime.utcnow()
    
    def reduce_quantity(self, quantity: Decimal) -> Decimal:
        """Reduzir quantidade da posição e retornar P&L realizado"""
        if quantity <= 0:
            raise ValueError("Quantidade deve ser positiva")
        
        if quantity > self.quantity:
            raise ValueError("Quantidade a reduzir maior que posição atual")
        
        # Calcular P&L realizado
        realized_pnl = (self.current_price - self.average_price) * quantity
        
        self.quantity -= quantity
        self.last_updated = datetime.utcnow()
        
        return realized_pnl
    
    def to_dict(self) -> dict:
        """Converter para dicionário"""
        return {
            'symbol': self.symbol,
            'quantity': str(self.quantity),
            'average_price': str(self.average_price),
            'current_price': str(self.current_price),
            'market_value': str(self.get_market_value()),
            'cost_basis': str(self.get_cost_basis()),
            'unrealized_pnl': str(self.get_unrealized_pnl()),
            'unrealized_pnl_percentage': self.get_unrealized_pnl_percentage(),
            'last_updated': self.last_updated.isoformat()
        }

@dataclass
class Portfolio:
    """Entidade Portfolio do domínio"""
    
    id: Optional[int]
    user_id: int
    name: str
    
    # Saldos
    cash_balance: Decimal = Decimal('0')
    initial_balance: Decimal = Decimal('0')
    
    # Posições
    positions: Dict[str, Position] = field(default_factory=dict)
    
    # Status e timestamps
    status: PortfolioStatus = PortfolioStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    # Métricas de performance
    total_realized_pnl: Decimal = Decimal('0')
    total_fees_paid: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    peak_value: Decimal = Decimal('0')
    
    # Configurações de risco
    max_position_size: Decimal = Decimal('0.1')  # 10% por posição
    max_portfolio_risk: Decimal = Decimal('0.02')  # 2% de risco total
    
    def __post_init__(self):
        """Validações após inicialização"""
        if self.initial_balance <= 0:
            self.initial_balance = self.cash_balance
        
        if self.peak_value == 0:
            self.peak_value = self.get_total_value()
    
    def is_active(self) -> bool:
        """Verificar se o portfólio está ativo"""
        return self.status == PortfolioStatus.ACTIVE
    
    def get_total_value(self) -> Decimal:
        """Obter valor total do portfólio"""
        positions_value = sum(pos.get_market_value() for pos in self.positions.values())
        return self.cash_balance + positions_value
    
    def get_total_cost_basis(self) -> Decimal:
        """Obter custo base total"""
        positions_cost = sum(pos.get_cost_basis() for pos in self.positions.values())
        return positions_cost
    
    def get_total_unrealized_pnl(self) -> Decimal:
        """Obter P&L não realizado total"""
        return sum(pos.get_unrealized_pnl() for pos in self.positions.values())
    
    def get_total_pnl(self) -> Decimal:
        """Obter P&L total (realizado + não realizado)"""
        return self.total_realized_pnl + self.get_total_unrealized_pnl()
    
    def get_total_return(self) -> float:
        """Obter retorno total em percentual"""
        if self.initial_balance == 0:
            return 0.0
        
        current_value = self.get_total_value()
        return float((current_value - self.initial_balance) / self.initial_balance * 100)
    
    def get_cash_percentage(self) -> float:
        """Obter percentual em cash"""
        total_value = self.get_total_value()
        if total_value == 0:
            return 100.0
        return float(self.cash_balance / total_value * 100)
    
    def get_position_percentage(self, symbol: str) -> float:
        """Obter percentual de uma posição específica"""
        if symbol not in self.positions:
            return 0.0
        
        total_value = self.get_total_value()
        if total_value == 0:
            return 0.0
        
        position_value = self.positions[symbol].get_market_value()
        return float(position_value / total_value * 100)
    
    def can_open_position(self, symbol: str, value: Decimal) -> bool:
        """Verificar se pode abrir uma posição"""
        if not self.is_active():
            return False
        
        # Verificar se tem cash suficiente
        if value > self.cash_balance:
            return False
        
        # Verificar limite de posição
        total_value = self.get_total_value()
        if total_value > 0:
            position_percentage = value / total_value
            if position_percentage > self.max_position_size:
                return False
        
        return True
    
    def add_cash(self, amount: Decimal) -> None:
        """Adicionar cash ao portfólio"""
        if amount <= 0:
            raise ValueError("Valor deve ser positivo")
        
        self.cash_balance += amount
        self.updated_at = datetime.utcnow()
    
    def withdraw_cash(self, amount: Decimal) -> None:
        """Retirar cash do portfólio"""
        if amount <= 0:
            raise ValueError("Valor deve ser positivo")
        
        if amount > self.cash_balance:
            raise ValueError("Saldo insuficiente")
        
        self.cash_balance -= amount
        self.updated_at = datetime.utcnow()
    
    def open_position(self, symbol: str, quantity: Decimal, price: Decimal) -> None:
        """Abrir nova posição ou adicionar à existente"""
        total_cost = quantity * price
        
        if not self.can_open_position(symbol, total_cost):
            raise ValueError("Não é possível abrir esta posição")
        
        # Deduzir do cash
        self.cash_balance -= total_cost
        
        # Adicionar ou atualizar posição
        if symbol in self.positions:
            self.positions[symbol].add_quantity(quantity, price)
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                average_price=price,
                current_price=price
            )
        
        self.updated_at = datetime.utcnow()
    
    def close_position(self, symbol: str, quantity: Decimal, price: Decimal, fees: Decimal = Decimal('0')) -> Decimal:
        """Fechar posição parcial ou total"""
        if symbol not in self.positions:
            raise ValueError(f"Posição {symbol} não encontrada")
        
        position = self.positions[symbol]
        
        if quantity > position.quantity:
            raise ValueError("Quantidade maior que posição atual")
        
        # Calcular P&L realizado
        realized_pnl = position.reduce_quantity(quantity)
        
        # Adicionar ao cash (valor de venda - taxas)
        cash_received = (quantity * price) - fees
        self.cash_balance += cash_received
        
        # Atualizar métricas
        self.total_realized_pnl += realized_pnl
        self.total_fees_paid += fees
        
        # Remover posição se quantidade for zero
        if position.quantity == 0:
            del self.positions[symbol]
        
        self.updated_at = datetime.utcnow()
        
        return realized_pnl
    
    def update_position_price(self, symbol: str, price: Decimal) -> None:
        """Atualizar preço de uma posição"""
        if symbol in self.positions:
            self.positions[symbol].update_price(price)
            self.updated_at = datetime.utcnow()
            
            # Atualizar métricas de drawdown
            self._update_drawdown_metrics()
    
    def update_all_prices(self, prices: Dict[str, Decimal]) -> None:
        """Atualizar preços de todas as posições"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].update_price(price)
        
        self.updated_at = datetime.utcnow()
        self._update_drawdown_metrics()
    
    def _update_drawdown_metrics(self) -> None:
        """Atualizar métricas de drawdown"""
        current_value = self.get_total_value()
        
        # Atualizar pico
        if current_value > self.peak_value:
            self.peak_value = current_value
        
        # Calcular drawdown atual
        if self.peak_value > 0:
            current_drawdown = (self.peak_value - current_value) / self.peak_value
            if current_drawdown > self.max_drawdown:
                self.max_drawdown = current_drawdown
    
    def get_positions_summary(self) -> List[dict]:
        """Obter resumo de todas as posições"""
        return [pos.to_dict() for pos in self.positions.values()]
    
    def get_risk_metrics(self) -> dict:
        """Obter métricas de risco"""
        total_value = self.get_total_value()
        
        return {
            'total_value': str(total_value),
            'cash_percentage': self.get_cash_percentage(),
            'max_drawdown': float(self.max_drawdown * 100),
            'total_return': self.get_total_return(),
            'sharpe_ratio': 0.0,  # TODO: Implementar cálculo
            'volatility': 0.0,    # TODO: Implementar cálculo
            'positions_count': len(self.positions),
            'largest_position_percentage': max(
                [self.get_position_percentage(symbol) for symbol in self.positions.keys()],
                default=0.0
            )
        }
    
    def to_dict(self) -> dict:
        """Converter para dicionário"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'cash_balance': str(self.cash_balance),
            'initial_balance': str(self.initial_balance),
            'total_value': str(self.get_total_value()),
            'total_pnl': str(self.get_total_pnl()),
            'total_return': self.get_total_return(),
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'positions': self.get_positions_summary(),
            'risk_metrics': self.get_risk_metrics()
        }

