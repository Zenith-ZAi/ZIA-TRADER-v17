import asyncio

from config.settings import Settings
from database import MarketType
from database_manager import DatabaseManager
from execution.execution_engine import ExecutionEngine


class FakeRedis:
    def __init__(self):
        self.states = {}

    async def set_state(self, key, value, expire=None):
        self.states[key] = value

    async def get_state(self, key):
        return self.states.get(key)

    async def delete_state(self, key):
        self.states.pop(key, None)


class FakeExchange:
    async def place_order(self, symbol, action, order_type, quantity, price=None):
        return {
            "status": "success",
            "order_id": "order-1",
            "filled_price": 101.25,
            "filled_quantity": quantity,
            "commission": 0.01,
        }


def test_filled_entry_persists_rich_position_state(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'execution.db'}")
    db.create_tables()
    redis_cache = FakeRedis()
    executor = ExecutionEngine(
        Settings(DATABASE_URL=f"sqlite:///{tmp_path / 'execution.db'}"),
        FakeExchange(),
        redis_cache,
        db_manager=db,
        account_id="test-account",
    )

    result = asyncio.run(
        executor.execute_order(
            {
                "symbol": "BTC/USDT",
                "action": "buy",
                "quantity": 0.1,
                "price": 100.0,
                "stop_loss": 98.0,
                "take_profit": 104.0,
                "breakeven_trigger": 102.0,
                "market_type": MarketType.CRYPTO,
            }
        )
    )

    assert result["status"] == "success"
    state = redis_cache.states["position_BTC/USDT"]
    assert state["entry_price"] == 101.25
    assert state["stop_loss"] == 98.0
    assert state["take_profit"] == 104.0
    positions = db.get_open_positions("test-account")
    assert len(positions) == 1
    assert positions[0].market_type is MarketType.CRYPTO
    assert positions[0].entry_price == 101.25
    runtime_positions = db.get_open_runtime_positions("test-account")
    assert len(runtime_positions) == 1
    assert runtime_positions[0].take_profit == 104.0


def test_filled_exit_clears_position_state_and_database(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'execution-exit.db'}")
    db.create_tables()
    db.create_position("test-account", "BTC/USDT", MarketType.CRYPTO, 0.1, 100.0, 100.0)
    redis_cache = FakeRedis()
    redis_cache.states["position_BTC/USDT"] = {"symbol": "BTC/USDT", "action": "buy"}
    executor = ExecutionEngine(
        Settings(DATABASE_URL=f"sqlite:///{tmp_path / 'execution-exit.db'}"),
        FakeExchange(),
        redis_cache,
        db_manager=db,
        account_id="test-account",
    )

    result = asyncio.run(
        executor.execute_order(
            {
                "symbol": "BTC/USDT",
                "action": "sell",
                "quantity": 0.1,
                "price": 104.0,
                "exit_reason": "take_profit",
            }
        )
    )

    assert result["status"] == "success"
    assert "position_BTC/USDT" not in redis_cache.states
    assert db.get_open_positions("test-account") == []
    assert db.get_open_runtime_positions("test-account") == []
