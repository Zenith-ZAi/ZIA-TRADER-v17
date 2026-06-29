import pytest
import os
from datetime import datetime
from database_manager import DatabaseManager
from config.settings import Settings
from database import AccountState, Position, DailyPNL, Drawdown, OrderHistory, ExecutionHistory, SystemLog, MarketType, OrderStatus

# Configurações para o ambiente de teste
@pytest.fixture(scope="module")
def test_settings():
    # Usar um banco de dados SQLite em memória para testes
    settings = Settings(
        DATABASE_URL="sqlite:////tmp/test_zia_trader.db",
        # Outras configurações podem ser mockadas ou definidas conforme necessário
    )
    return settings

@pytest.fixture(scope="module")
def db_manager(test_settings):
    manager = DatabaseManager(test_settings.DATABASE_URL)
    # Garantir que o banco de dados esteja limpo antes de cada teste
    db_path = test_settings.DATABASE_URL.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    manager.create_tables()
    yield manager
    # Limpar o banco de dados após os testes
    if os.path.exists(db_path):
        os.remove(db_path)

def test_create_tables(db_manager):
    # Se não houver exceções, as tabelas foram criadas com sucesso
    assert True

def test_create_or_update_account_state(db_manager):
    account_id = "test_account_1"
    initial_capital = 1000.0
    balance = 1000.0
    db_manager.create_or_update_account_state(account_id, balance, initial_capital)
    state = db_manager.get_account_state(account_id)
    assert state is not None
    assert state.account_id == account_id
    assert state.initial_capital == initial_capital
    assert state.balance == balance

    # Atualizar estado
    new_balance = 1200.0
    db_manager.create_or_update_account_state(account_id, new_balance, initial_capital)
    updated_state = db_manager.get_account_state(account_id)
    assert updated_state.balance == new_balance

def test_create_position(db_manager):
    account_id = "test_account_2"
    symbol = "BTC/USDT"
    quantity = 0.1
    entry_price = 50000.0
    position_type = "long"
    db_manager.create_position(account_id, symbol, MarketType.CRYPTO, quantity, entry_price, entry_price)
    positions = db_manager.get_open_positions(account_id)
    assert len(positions) == 1
    assert positions[0].symbol == symbol

def test_close_position(db_manager):
    account_id = "test_account_3"
    symbol = "ETH/USDT"
    quantity = 0.5
    entry_price = 3000.0
    position_type = "long"
    db_manager.create_position(account_id, symbol, MarketType.CRYPTO, quantity, entry_price, entry_price)
    
    db_manager.close_position(account_id, symbol)
    positions = db_manager.get_open_positions(account_id)
    assert len(positions) == 0

def test_create_pnl(db_manager):
    account_id = "test_account_4"
    symbol = "SOL/USDT"
    pnl_value = 50.0
    timestamp = datetime.now()
    db_manager.create_pnl(account_id, symbol, pnl_value, timestamp)
    pnls = db_manager.get_pnl_history(account_id)
    assert len(pnls) == 1
    assert pnls[0].pnl == pnl_value

def test_create_drawdown(db_manager):
    account_id = "test_account_5"
    drawdown_value = -100.0
    timestamp = datetime.now()
    db_manager.create_drawdown(account_id, drawdown_value, timestamp)
    drawdowns = db_manager.get_drawdown_history(account_id)
    assert len(drawdowns) == 1
    assert drawdowns[0].drawdown == drawdown_value

def test_create_order_history(db_manager):
    account_id = "test_account_6"
    order_id = "order_123"
    symbol = "ADA/USDT"
    order_type = "limit"
    action = "buy"
    price = 1.0
    quantity = 100.0
    timestamp = datetime.now()
    db_manager.create_order_history(account_id, order_id, symbol, MarketType.CRYPTO, action, order_type, price, quantity, OrderStatus.FILLED)
    orders = db_manager.get_order_history(account_id)
    assert len(orders) == 1
    assert orders[0].order_id == order_id

def test_create_execution_history(db_manager):
    account_id = "test_account_7"
    execution_id = "exec_456"
    order_id = "order_456"
    symbol = "XRP/USDT"
    market_type = MarketType.CRYPTO
    action = "sell"
    filled_price = 0.5
    filled_quantity = 200.0
    commission = 0.1
    timestamp = datetime.now()
    db_manager.create_execution_history(account_id, execution_id, order_id, symbol, market_type, action, filled_price, filled_quantity, commission, metadata_json={"timestamp": timestamp.isoformat()})
    executions = db_manager.get_execution_history(account_id)
    assert len(executions) == 1
    assert executions[0].execution_id == execution_id

def test_create_system_log(db_manager):
    account_id = "test_account_8"
    level = "INFO"
    message = "Sistema iniciado."
    source = "main"
    timestamp = datetime.now()
    db_manager.create_system_log(level, message, source, account_id)
    logs = db_manager.get_system_logs(account_id)
    assert len(logs) == 1
    assert logs[0].message == message
