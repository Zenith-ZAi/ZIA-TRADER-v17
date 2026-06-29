from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from database import Base, AccountState, Position, DailyPNL, WeeklyPNL, MonthlyPNL, Drawdown, OrderHistory, ExecutionHistory, Trade, WhaleActivity, SystemLog, MarketType, OrderStatus

class DatabaseManager:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False} if "sqlite" in database_url else {})
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self):
        Base.metadata.create_all(self.engine)

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # AccountState Operations
    def create_or_update_account_state(self, account_id: str, balance: float, initial_capital: float) -> AccountState:
        db = self.SessionLocal()
        account_state = db.query(AccountState).filter(AccountState.account_id == account_id).first()
        if account_state:
            account_state.balance = balance
            account_state.initial_capital = initial_capital
        else:
            account_state = AccountState(account_id=account_id, balance=balance, initial_capital=initial_capital)
            db.add(account_state)
        db.commit()
        db.refresh(account_state)
        db.close()
        return account_state

    def get_account_state(self, account_id: str) -> Optional[AccountState]:
        db = self.SessionLocal()
        account_state = db.query(AccountState).filter(AccountState.account_id == account_id).first()
        db.close()
        return account_state

    # Position Operations
    def create_position(self, account_id: str, symbol: str, market_type: MarketType, quantity: float, entry_price: float, current_price: float) -> Position:
        db = self.SessionLocal()
        position = Position(account_id=account_id, symbol=symbol, market_type=market_type, quantity=quantity, entry_price=entry_price, current_price=current_price)
        db.add(position)
        db.commit()
        db.refresh(position)
        db.close()
        return position

    def update_position(self, position_id: int, current_price: float, unrealized_pnl: float, realized_pnl: float, is_open: bool, close_time: Optional[datetime] = None) -> Optional[Position]:
        db = self.SessionLocal()
        position = db.query(Position).filter(Position.id == position_id).first()
        if position:
            position.current_price = current_price
            position.unrealized_pnl = unrealized_pnl
            position.realized_pnl = realized_pnl
            position.is_open = is_open
            position.close_time = close_time
            db.commit()
            db.refresh(position)
        db.close()
        return position

    def get_open_positions(self, account_id: str) -> List[Position]:
        db = self.SessionLocal()
        positions = db.query(Position).filter(Position.account_id == account_id, Position.is_open == True).all()
        db.close()
        return positions

    def close_position(self, account_id: str, symbol: str) -> Optional[Position]:
        db = self.SessionLocal()
        position = db.query(Position).filter(Position.account_id == account_id, Position.symbol == symbol, Position.is_open == True).first()
        if position:
            position.is_open = False
            position.close_time = datetime.utcnow()
            db.commit()
            db.refresh(position)
        db.close()
        return position

    # PnL Operations
    def create_pnl(self, account_id: str, symbol: str, pnl_value: float, timestamp: datetime) -> DailyPNL:
        db = self.SessionLocal()
        pnl_entry = DailyPNL(account_id=account_id, date=timestamp.date(), pnl=pnl_value)
        db.add(pnl_entry)
        db.commit()
        db.refresh(pnl_entry)
        db.close()
        return pnl_entry

    def get_pnl_history(self, account_id: str) -> List[DailyPNL]:
        db = self.SessionLocal()
        pnls = db.query(DailyPNL).filter(DailyPNL.account_id == account_id).order_by(DailyPNL.date.desc()).all()
        db.close()
        return pnls

    # Drawdown Operations
    def create_drawdown(self, account_id: str, drawdown_value: float, timestamp: datetime) -> Drawdown:
        db = self.SessionLocal()
        drawdown_entry = Drawdown(account_id=account_id, start_time=timestamp, peak_balance=0.0, trough_balance=0.0, max_drawdown_percentage=0.0, drawdown=drawdown_value) # Simplified
        db.add(drawdown_entry)
        db.commit()
        db.refresh(drawdown_entry)
        db.close()
        return drawdown_entry

    def get_drawdown_history(self, account_id: str) -> List[Drawdown]:
        db = self.SessionLocal()
        drawdowns = db.query(Drawdown).filter(Drawdown.account_id == account_id).order_by(Drawdown.start_time.desc()).all()
        db.close()
        return drawdowns

    # PNL Operations
    def create_or_update_daily_pnl(self, account_id: str, date: datetime, pnl: float, drawdown: float) -> DailyPNL:
        db = self.SessionLocal()
        daily_pnl = db.query(DailyPNL).filter(DailyPNL.account_id == account_id, DailyPNL.date == date.date()).first()
        if daily_pnl:
            daily_pnl.pnl = pnl
            daily_pnl.drawdown = drawdown
        else:
            daily_pnl = DailyPNL(account_id=account_id, date=date.date(), pnl=pnl, drawdown=drawdown)
            db.add(daily_pnl)
        db.commit()
        db.refresh(daily_pnl)
        db.close()
        return daily_pnl

    def get_daily_pnl(self, account_id: str, date: datetime) -> Optional[DailyPNL]:
        db = self.SessionLocal()
        daily_pnl = db.query(DailyPNL).filter(DailyPNL.account_id == account_id, DailyPNL.date == date.date()).first()
        db.close()
        return daily_pnl

    # OrderHistory Operations
    def create_order_history(self, account_id: str, order_id: str, symbol: str, market_type: MarketType, action: str, order_type: str, price: Optional[float], quantity: Optional[float], status: OrderStatus, metadata_json: Optional[dict] = None) -> OrderHistory:
        db = self.SessionLocal()
        order_history = OrderHistory(account_id=account_id, order_id=order_id, symbol=symbol, market_type=market_type, action=action, order_type=order_type, price=price, quantity=quantity, status=status, metadata_json=metadata_json)
        db.add(order_history)
        db.commit()
        db.refresh(order_history)
        db.close()
        return order_history

    def update_order_status(self, order_id: str, status: OrderStatus) -> Optional[OrderHistory]:
        db = self.SessionLocal()
        order_history = db.query(OrderHistory).filter(OrderHistory.order_id == order_id).first()
        if order_history:
            order_history.status = status
            db.commit()
            db.refresh(order_history)
        db.close()
        return order_history

    def get_order_history(self, account_id: str) -> List[OrderHistory]:
        db = self.SessionLocal()
        orders = db.query(OrderHistory).filter(OrderHistory.account_id == account_id).order_by(OrderHistory.timestamp.desc()).all()
        db.close()
        return orders

    # ExecutionHistory Operations
    def create_execution_history(self, account_id: str, execution_id: str, order_id: str, symbol: str, market_type: MarketType, action: str, filled_price: float, filled_quantity: float, commission: float, metadata_json: Optional[dict] = None) -> ExecutionHistory:
        db = self.SessionLocal()
        execution_history = ExecutionHistory(account_id=account_id, execution_id=execution_id, order_id=order_id, symbol=symbol, market_type=market_type, action=action, filled_price=filled_price, filled_quantity=filled_quantity, commission=commission, metadata_json=metadata_json)
        db.add(execution_history)
        db.commit()
        db.refresh(execution_history)
        db.close()
        return execution_history

    def get_execution_history(self, account_id: str) -> List[ExecutionHistory]:
        db = self.SessionLocal()
        executions = db.query(ExecutionHistory).filter(ExecutionHistory.account_id == account_id).order_by(ExecutionHistory.timestamp.desc()).all()
        db.close()
        return executions

    # SystemLog Operations
    def create_system_log(self, level: str, message: str, module: str, account_id: Optional[str] = None) -> SystemLog:
        db = self.SessionLocal()
        system_log = SystemLog(level=level, message=message, module=module, account_id=account_id)
        db.add(system_log)
        db.commit()
        db.refresh(system_log)
        db.close()
        return system_log

    def get_system_logs(self, account_id: str = None) -> List[SystemLog]:
        db = self.SessionLocal()
        if account_id:
            logs = db.query(SystemLog).filter(SystemLog.account_id == account_id).order_by(SystemLog.timestamp.desc()).all()
        else:
            logs = db.query(SystemLog).order_by(SystemLog.timestamp.desc()).all()
        db.close()
        return logs

    # Utility for PNL calculations (simplified for now)
    def calculate_pnl_metrics(self, account_id: str, end_date: datetime) -> Dict[str, float]:
        db = self.SessionLocal()
        # Placeholder for actual PNL, drawdown, etc. calculation logic
        # This would involve querying trades, positions, etc.
        total_pnl = 0.0
        current_balance = self.get_account_state(account_id).balance if self.get_account_state(account_id) else 0.0
        initial_capital = self.get_account_state(account_id).initial_capital if self.get_account_state(account_id) else 0.0

        if initial_capital > 0:
            total_pnl = current_balance - initial_capital

        # Simplified drawdown calculation
        drawdown = 0.0 # This needs proper implementation based on historical balance

        db.close()
        return {"total_pnl": total_pnl, "drawdown": drawdown}
