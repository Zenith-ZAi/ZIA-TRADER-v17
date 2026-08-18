# ZIA-TRADER-v17

An algorithmic trading bot with a FastAPI backend, AI ensemble models (Transformer, LSTM, XGBoost, RandomForest), JWT authentication, Prometheus metrics, and a simulated exchange connector.

## How to run

The workflow **"Start application"** starts the FastAPI server:

```
python main.py
```

The API is available on **port 8000**. Background trading engines are **not started automatically by default**; set `AUTO_START_ENGINES=true` only for an intentional simulation or controlled deployment.

## Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/token` | Get a JWT token (form: `username` + `password`) |
| GET | `/users/me` | Current authenticated user |
| GET | `/admin/dashboard` | Admin-only dashboard |
| GET | `/healthz` | Liveness and provider status |
| GET | `/metrics` | Prometheus metrics |
| POST | `/trading/start` | Start the trading engine once |
| POST | `/sniper/start` | Start the Sniper engine once |
| POST | `/trading/stop` | Stop all engines and background tasks |
| GET | `/docs` | Interactive Swagger UI |

**Demo credentials** (defined in `main.py` → `FAKE_USERS_DB`):
- `user` / `password` — trader role
- `admin` / `admin` — admin + trader roles

## Stack

- **FastAPI** + **Uvicorn** — HTTP server (port 8000)
- **SQLAlchemy** — ORM; connected to Replit's built-in PostgreSQL (`DATABASE_URL` env var)
- **Redis** — used for price caching; falls back to in-memory when Redis is unavailable
- **PyTorch** — Transformer and LSTM models
- **XGBoost / scikit-learn** — ensemble predictions
- **Prometheus** — metrics at `/metrics`
- **OpenTelemetry** — distributed tracing (gracefully disabled when collector is unreachable)

## Project layout

```
main.py                  FastAPI app, auth, healthcheck, lifecycle
worker.py                Dedicated process for trading and Sniper engines
config/settings.py       All config (env vars + defaults)
core/
  engine.py              RoboTraderUnified — main trading loop
  sniper_engine.py       High-frequency sniper engine
  manager.py             Orchestrates all engines
  backtest_engine.py     Backtesting
ai/
  ensemble_model.py      Combines Transformer, LSTM, XGBoost, RF
  whale_detector.py      Large-order activity detection
  price_transformer_model.py
  price_lstm_model.py
execution/
  exchange_connector.py  Simulated exchange (swap for real ccxt)
  execution_engine.py    Order routing
infra/redis_cache.py     Redis with in-memory fallback
database.py              SQLAlchemy models
database_manager.py      DB CRUD helpers
security/                JWT, RBAC, rate limiter
monitoring/              Prometheus metrics + OpenTelemetry
data/news_processor.py   Free/paid news and trend providers with cache
core/market_signals.py   Explainable market reading and signal gate
risk/risk_ai.py          Risk validation and exposure limits
core/backtest_engine.py  Walk-forward backtest with drawdown and Sharpe
```

## Environment variables

Defined in `.env` (loaded automatically by pydantic-settings):

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | SQLite fallback | Set a managed database URL in deployment |
| `REDIS_URL` | `redis://localhost:6379/0` | Falls back to in-memory |
| `ENVIRONMENT` | `development` | `production` disables demo authentication |
| `AUTO_START_ENGINES` | `false` | Explicit opt-in for background engines |
| `DEMO_AUTH_ENABLED` | `true` | Development-only authentication switch |
| `DEMO_USER_PASSWORD` / `DEMO_ADMIN_PASSWORD` | — | Configure demo passwords locally |
| `AUTH_MODE` | `demo` | Use `env` in production |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | — | Required when `AUTH_MODE=env` |
| `SECRET_KEY` | `dev-only-change-me` | **Replace with a long random value outside development** |
| `BINANCE_MODE` | `simulated` | Use `testnet` or `demo` only with sandbox credentials |
| `BINANCE_BASE_URL` | `https://testnet.binance.vision/api` | Must remain a documented sandbox host |
| `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` | — | Testnet/Demo credentials; never production keys |
| `BINANCE_TIMEOUT_SECONDS` / `BINANCE_RECV_WINDOW_MS` | `10` / `5000` | Network timeout and signed-request window |
| `GDELT_BASE_URL` | Official GDELT DOC API | Free news fallback |
| `COINGECKO_BASE_URL` / `COINGECKO_API_KEY` | Public API / optional Pro key | Trending assets with cache |
| `ALPHA_VANTAGE_API_KEY` | — | Optional market news and sentiment |
| `BENZINGA_API_KEY` | — | Optional licensed news feed |
| `NEWSAPI_API_KEY` | — | Optional article discovery |
| `CRYPTOPANIC_API_KEY` | — | Optional paid crypto news and PanicScore |

## Validation and deployment

The final validation command is `python -m pytest -q`; the current suite covers API authentication, database CRUD, market signal rejection, deterministic backtest, risk limits, provider fallback, and idempotent news/trend persistence. The production composition separates `main.py` (HTTP API) from `worker.py` (trading engines), uses PostgreSQL and Redis, and requires `SECRET_KEY` and `POSTGRES_PASSWORD` to be injected by the deployment environment. The GitHub Actions workflow compiles the code, runs the tests, and builds the container; it does not publish or activate live trading automatically.

The repository launcher is `start.sh`. Use `ZIA_MODE=test ./start.sh` for the offline regression suite, `ZIA_MODE=api ./start.sh` for the HTTP service, or `ZIA_MODE=worker ./start.sh` for the persistent worker. The launcher intentionally contains no exchange credentials; inject them through the server secret manager or a local ignored `.env` file.

The exchange facade supports `BINANCE_MODE=simulated` (default), `BINANCE_MODE=testnet` with `https://testnet.binance.vision/api`, and `BINANCE_MODE=demo` with `https://demo-api.binance.com/api`. The real adapter rejects unknown or production hosts, signs HMAC requests, loads `exchangeInfo`, applies symbol filters and fetches account/market data. Keep order calls disabled until the sandbox smoke test passes; this repository does not provide a production adapter.

## Admin Console

A full CLI terminal for managing the system without editing files manually.

**Run it:** start the **"Admin Console"** workflow, or:
```
python admin_console.py
```

**Default credentials (change immediately):**
- Username: `admin`
- Password: `admin123`

The console forces a password change on first login.

### Modules

| # | Module | What it does |
|---|--------|-------------|
| 1 | Exchange APIs | Add/edit/delete/toggle Binance, Bybit, OKX, KuCoin, Bitget, Gate.io — API keys encrypted with Fernet (AES-128) |
| 2 | Usuários | Create users with roles (Admin/Operator/Reader/Guest), change passwords, block/unblock |
| 3 | Estratégias | Enable/disable and tune 15 strategies (VWAP, MACD, RSI, Smart Money, IA Adaptativa …) |
| 4 | IA | Train models, recalculate weights, load/save/export/import, benchmark, RL, auto-learning |
| 5 | Algoritmos | Configure 10 algorithm profiles (Conservative → HFT → Custom) |
| 6 | Configurações | Edit timeframes, risk limits, stop/take, sim vs production mode, infra settings |
| 7 | Logs | Browse/filter/export system logs by category; clean old records |
| 8 | Atualizações | Check outdated deps, update requirements, migrate DB, backup, rollback |
| 9 | Segurança | Rotate encryption key, change master password, revoke sessions, block IPs |
| 10 | Testes | Run all test suites with live progress bars and pass/fail report |

### CLI layout
```
cli/
  auth.py            login + bcrypt password hashing
  crypto_utils.py    Fernet encrypt/decrypt for API keys
  db_models.py       AdminUser, ExchangeConfig, StrategyConfig, AlgorithmConfig
  console.py         Shared Rich helpers (banner, menus, tables, progress bars)
  exchange_menu.py   Exchange management
  users_menu.py      User management
  strategies_menu.py Strategy configuration
  algorithms_menu.py Algorithm configuration
  ai_menu.py         AI/ML operations
  config_menu.py     System configuration (.env editor)
  logs_menu.py       Log viewer + exporter
  updates_menu.py    Updates, backup, rollback
  security_menu.py   Security operations
  tests_menu.py      Test runner
admin_console.py     Entry point
```

## User preferences

- Keep the existing project structure and stack; do not restructure or migrate.
