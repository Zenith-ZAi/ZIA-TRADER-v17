"""
Entidade Trade - Camada de Domínio
Representa uma operação de trading no sistema
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum
from decimal import Decimal

class TradeType(Enum):
    BUY = "buy"
    SELL = "sell"

class TradeStatus(Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    PARTIALLY_FILLED = "partially_filled"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"

@dataclass
class Trade:
    """Entidade Trade do domínio"""
    
    id: Optional[int]
    user_id: int
    symbol: str
    trade_type: TradeType
    order_type: OrderType
    
    # Quantidades e preços
    quantity: Decimal
    price: Optional[Decimal]  # None para market orders
    executed_price: Optional[Decimal] = None
    executed_quantity: Decimal = Decimal('0')
    
    # Status e timestamps
    status: TradeStatus = TradeStatus.PENDING
    created_at: datetime = None
    executed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    # Parâmetros de risco
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    
    # Informações adicionais
    exchange: Optional[str] = None
    external_order_id: Optional[str] = None
    fees: Decimal = Decimal('0')
    notes: Optional[str] = None
    
    # Análise e sinais
    confidence_score: Optional[float] = None
    ai_signal_strength: Optional[float] = None
    strategy_used: Optional[str] = None
    
    def __post_init__(self):
        """Validações após inicialização"""
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        
        if self.quantity <= 0:
            raise ValueError("Quantidade deve ser positiva")
        
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Preço é obrigatório para ordens limit")
        
        if self.order_type == OrderType.STOP_LOSS and self.stop_loss is None:
            raise ValueError("Stop loss é obrigatório para ordens stop loss")
        
        if self.order_type == OrderType.TAKE_PROFIT and self.take_profit is None:
            raise ValueError("Take profit é obrigatório para ordens take profit")
    
    def is_pending(self) -> bool:
        """Verificar se o trade está pendente"""
        return self.status == TradeStatus.PENDING
    
    def is_executed(self) -> bool:
        """Verificar se o trade foi executado"""
        return self.status == TradeStatus.EXECUTED
    
    def is_cancelled(self) -> bool:
        """Verificar se o trade foi cancelado"""
        return self.status == TradeStatus.CANCELLED
    
    def is_failed(self) -> bool:
        """Verificar se o trade falhou"""
        return self.status == TradeStatus.FAILED
    
    def is_partially_filled(self) -> bool:
        """Verificar se o trade foi parcialmente executado"""
        return self.status == TradeStatus.PARTIALLY_FILLED
    
    def can_be_cancelled(self) -> bool:
        """Verificar se o trade pode ser cancelado"""
        return self.status in [TradeStatus.PENDING, TradeStatus.PARTIALLY_FILLED]
    
    def execute(self, executed_price: Decimal, executed_quantity: Decimal, fees: Decimal = Decimal('0')) -> None:
        """Executar o trade"""
        if not self.is_pending() and not self.is_partially_filled():
            raise ValueError("Trade não pode ser executado no status atual")
        
        self.executed_price = executed_price
        self.executed_quantity += executed_quantity
        self.fees += fees
        self.executed_at = datetime.utcnow()
        
        # Determinar status final
        if self.executed_quantity >= self.quantity:
            self.status = TradeStatus.EXECUTED
        else:
            self.status = TradeStatus.PARTIALLY_FILLED
    
    def cancel(self, reason: Optional[str] = None) -> None:
        """Cancelar o trade"""
        if not self.can_be_cancelled():
            raise ValueError("Trade não pode ser cancelado no status atual")
        
        self.status = TradeStatus.CANCELLED
        self.cancelled_at = datetime.utcnow()
        if reason:
            self.notes = f"{self.notes or ''} | Cancelado: {reason}".strip(' |')
    
    def fail(self, reason: Optional[str] = None) -> None:
        """Marcar trade como falhado"""
        self.status = TradeStatus.FAILED
        if reason:
            self.notes = f"{self.notes or ''} | Falha: {reason}".strip(' |')
    
    def get_total_value(self) -> Decimal:
        """Obter valor total do trade"""
        if self.executed_price and self.executed_quantity:
            return self.executed_price * self.executed_quantity
        elif self.price:
            return self.price * self.quantity
        else:
            return Decimal('0')
    
    def get_net_value(self) -> Decimal:
        """Obter valor líquido (descontando taxas)"""
        return self.get_total_value() - self.fees
    
    def get_fill_percentage(self) -> float:
        """Obter percentual de execução"""
        if self.quantity == 0:
            return 0.0
        return float(self.executed_quantity / self.quantity * 100)
    
    def get_remaining_quantity(self) -> Decimal:
        """Obter quantidade restante para execução"""
        return self.quantity - self.executed_quantity
    
    def calculate_pnl(self, current_price: Decimal) -> Decimal:
        """Calcular P&L baseado no preço atual"""
        if not self.is_executed():
            return Decimal('0')
        
        if self.trade_type == TradeType.BUY:
            return (current_price - self.executed_price) * self.executed_quantity - self.fees
        else:  # SELL
            return (self.executed_price - current_price) * self.executed_quantity - self.fees
    
    def should_trigger_stop_loss(self, current_price: Decimal) -> bool:
        """Verificar se deve acionar stop loss"""
        if not self.stop_loss or not self.is_executed():
            return False
        
        if self.trade_type == TradeType.BUY:
            return current_price <= self.stop_loss
        else:  # SELL
            return current_price >= self.stop_loss
    
    def should_trigger_take_profit(self, current_price: Decimal) -> bool:
        """Verificar se deve acionar take profit"""
        if not self.take_profit or not self.is_executed():
            return False
        
        if self.trade_type == TradeType.BUY:
            return current_price >= self.take_profit
        else:  # SELL
            return current_price <= self.take_profit
    
    def to_dict(self) -> dict:
        """Converter para dicionário"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'trade_type': self.trade_type.value,
            'order_type': self.order_type.value,
            'quantity': str(self.quantity),
            'price': str(self.price) if self.price else None,
            'executed_price': str(self.executed_price) if self.executed_price else None,
            'executed_quantity': str(self.executed_quantity),
            'status': self.status.value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
            'stop_loss': str(self.stop_loss) if self.stop_loss else None,
            'take_profit': str(self.take_profit) if self.take_profit else None,
            'exchange': self.exchange,
            'external_order_id': self.external_order_id,
            'fees': str(self.fees),
            'notes': self.notes,
            'confidence_score': self.confidence_score,
            'ai_signal_strength': self.ai_signal_strength,
            'strategy_used': self.strategy_used,
            'total_value': str(self.get_total_value()),
            'net_value': str(self.get_net_value()),
            'fill_percentage': self.get_fill_percentage(),
            'remaining_quantity': str(self.get_remaining_quantity())
        }

