import pytest
from unittest.mock import AsyncMock, MagicMock
from enhanced_broker_api import EnhancedBrokerAPI
import pandas as pd

@pytest.fixture
def mock_config():
    mock = MagicMock()
    mock.api.exchange_name = "test_exchange"
    mock.api.sandbox_mode = True
    mock.api.api_key = "test_key"
    mock.api.api_secret = "test_secret"
    mock.api.api_passphrase = "test_passphrase"
    return mock

@pytest.fixture
def broker_api(mock_config):
    # Mock the ccxt exchange object
    mock_exchange = AsyncMock()
    mock_exchange.load_markets = AsyncMock(return_value=True)
    mock_exchange.fetch_balance = AsyncMock(return_value={
        'free': {'USDT': 1000},
        'used': {'USDT': 0},
        'total': {'USDT': 1000}
    })
    mock_exchange.fetch_ohlcv = AsyncMock(return_value=[
        [1678886400000, 100, 105, 98, 102, 1000],
        [1678886460000, 102, 108, 100, 105, 1200]
    ])
    mock_exchange.create_order = AsyncMock(return_value={'id': 'order123'})
    mock_exchange.cancel_order = AsyncMock(return_value={'status': 'canceled'})
    mock_exchange.fetch_order = AsyncMock(return_value={'status': 'closed'})

    # Patch the ccxt.exchange_name to return our mock_exchange
    with pytest.MonkeyPatch().context() as m:
        m.setattr("ccxt.test_exchange", MagicMock(return_value=mock_exchange))
        api = EnhancedBrokerAPI(mock_config.api.exchange_name, mock_config.api.sandbox_mode)
        api.exchange = mock_exchange # Manually set the mocked exchange
        yield api

@pytest.mark.asyncio
async def test_connect_success(broker_api):
    broker_api.exchange.set_sandbox_mode = MagicMock()
    connected = await broker_api.connect()
    assert connected is True
    broker_api.exchange.load_markets.assert_called_once()
    broker_api.exchange.set_sandbox_mode.assert_called_once_with(True)

@pytest.mark.asyncio
async def test_connect_failure(broker_api):
    broker_api.exchange.load_markets.side_effect = Exception("Connection error")
    connected = await broker_api.connect()
    assert connected is False

@pytest.mark.asyncio
async def test_get_account_balance(broker_api):
    balance = await broker_api.get_account_balance()
    assert balance == 1000
    broker_api.exchange.fetch_balance.assert_called_once()

@pytest.mark.asyncio
async def test_get_market_data_async(broker_api):
    df = await broker_api.get_market_data_async("BTC/USDT", "1m", 2)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert len(df) == 2
    assert "open" in df.columns
    broker_api.exchange.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1m", limit=2)

@pytest.mark.asyncio
async def test_execute_order_buy(broker_api):
    order_id = await broker_api.execute_order("BTC/USDT", "buy", 0.01, 40000)
    assert order_id == "order123"
    broker_api.exchange.create_order.assert_called_once_with("BTC/USDT", "limit", "buy", 0.01, 40000)

@pytest.mark.asyncio
async def test_execute_order_sell(broker_api):
    order_id = await broker_api.execute_order("BTC/USDT", "sell", 0.01, 40000)
    assert order_id == "order123"
    broker_api.exchange.create_order.assert_called_once_with("BTC/USDT", "limit", "sell", 0.01, 40000)

@pytest.mark.asyncio
async def test_execute_order_failure(broker_api):
    broker_api.exchange.create_order.side_effect = Exception("Order creation failed")
    order_id = await broker_api.execute_order("BTC/USDT", "buy", 0.01, 40000)
    assert order_id is None

@pytest.mark.asyncio
async def test_cancel_order(broker_api):
    status = await broker_api.cancel_order("order123", "BTC/USDT")
    assert status == "canceled"
    broker_api.exchange.cancel_order.assert_called_once_with("order123", "BTC/USDT")

@pytest.mark.asyncio
async def test_get_order_status(broker_api):
    status = await broker_api.get_order_status("order123", "BTC/USDT")
    assert status == "closed"
    broker_api.exchange.fetch_order.assert_called_once_with("order123", "BTC/USDT")


