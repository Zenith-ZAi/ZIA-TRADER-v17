---
name: testing-zia-trader-backend
description: Test the ZIA-TRADER-v17 FastAPI backend end-to-end. Use when verifying backend logic, database connection, API endpoints, or trade persistence changes.
---

# Testing ZIA-TRADER-v17 Backend

## Prerequisites

- Python 3.11+ with dependencies from `requirements.txt` installed
- No external services required (Redis, Kafka, Binance all have graceful fallbacks)

## Quick Start

```bash
cd /home/ubuntu/ZIA-TRADER-v17
pip install -r requirements.txt
rm -f zia_trader.db  # Clean slate for DB tests
python main.py       # Starts on port 8000
```

## Key Endpoints

| Method | Path | Purpose |
|--------|------|--------|
| GET | `/health` | Server status — returns `{"status": "online", "version": "17.0.0"}` |
| GET | `/` | Navigation info with links to docs, chat, WebSocket |
| POST | `/agent/chat` | Chat endpoint — body: `{"message": "...", "session_id": "default"}` |
| WS | `/agent/ws/{session_id}` | WebSocket chat (not in OpenAPI spec by design) |
| GET | `/learning/status` | Adaptive learning status |
| POST | `/learning/trigger` | Force a learning cycle |
| GET | `/docs` | Swagger UI |
| GET | `/openapi.json` | OpenAPI spec |

## Chat Commands

- `"status"` → Returns trading engine state ("Motor de trading: ativo/inativo")
- `"ajuda"` or `"help"` → Returns command list
- Any other message → Echo with suggestion to use status/ajuda

## Database Testing

The app uses async SQLAlchemy with SQLite (`zia_trader.db`) by default. Tables created on startup:
- `users` (id, username, email, hashed_password, is_active)
- `trades` (id, symbol, action, quantity, price, stop_loss, take_profit, pnl, timestamp, status, order_id, exit_price, exit_time)
- `news_articles` (id, symbol, title, content, sentiment_score, source, url, published_at)

To test trade persistence directly:
```python
import asyncio
from database import save_trade, close_trade_in_db, AsyncSessionLocal, Trade
from sqlalchemy import select

async def test():
    await save_trade({"symbol": "TEST/USDT", "action": "buy", "price": 100.0, "quantity": 1.0, "order_id": "test-001"})
    await close_trade_in_db("test-001", exit_price=110.0, pnl=10.0)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Trade).where(Trade.order_id == "test-001"))
        trade = result.scalar_one()
        assert trade.status == "closed"
        assert trade.exit_price == 110.0

asyncio.run(test())
```

## Expected Behaviors in Dev Environment

- **Binance API**: Will return HTTP 451 (geo-restricted) or auth errors without valid API keys. The trading loop logs warnings and retries every `ERROR_RETRY_INTERVAL` seconds. This is normal.
- **Redis**: Logs "Redis unavailable — using in-memory fallback" and works with an in-memory dict. All `set_state`/`get_state`/`update_price`/`get_price` methods work identically.
- **Kafka**: Consumer and producer use lazy initialization — they don't crash on import if Kafka is unavailable.
- **ANTHROPIC_API_KEY**: If not set, agent chat uses rule-based replies instead of LLM.

## Common Issues

- **sqlite3 CLI might not be installed** on the test VM. Use Python's `sqlite3` module instead for schema inspection.
- **WebSocket endpoints** are excluded from `/openapi.json` by FastAPI design. Test them separately with a WebSocket client.
- **Module-level imports**: If any new module tries to connect to external services at import time, it will crash the entire app. Always use lazy initialization.
- **f-strings with nested quotes**: Python < 3.12 doesn't support nested quotes in f-strings. Use `%` formatting or `.format()` for log messages with dict access.

## Devin Secrets Needed

No secrets required for basic backend testing. Optional:
- `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` — for live exchange testing
- `ANTHROPIC_API_KEY` — for LLM-powered agent chat
- `REDIS_URL` — only if testing with a real Redis instance
