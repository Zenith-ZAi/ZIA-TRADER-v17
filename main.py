import asyncio
from contextlib import asynccontextmanager
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from prometheus_client import generate_latest

from config.settings import settings
from core.manager import TradingManager
from database_manager import DatabaseManager
from monitoring.telemetry.telemetry_setup import setup_telemetry
from security.jwt_utils import create_access_token, verify_token
from security.rbac_utils import is_admin, is_trader
from risk.strategy_optimizer import OptimizationBudget, StrategyOptimizer
from api.middleware import RequestRateLimitMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


db_manager = DatabaseManager(settings.DATABASE_URL)
db_manager.create_tables()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Usuários de demonstração somente. Em produção, substitua esta camada pelo banco de usuários.
FAKE_USERS_DB: Dict[str, Dict[str, Any]] = {
    "user": {
        "username": "user",
        "password": settings.DEMO_USER_PASSWORD,
        "roles": ["trader"],
    },
    "admin": {
        "username": "admin",
        "password": settings.DEMO_ADMIN_PASSWORD,
        "roles": ["admin", "trader"],
    },
}

trading_manager = TradingManager(settings, db_manager)
engine_tasks: Dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Inicializa infraestrutura e encerra motores em ordem determinística."""
    logger.info("Iniciando %s v%s...", settings.PROJECT_NAME, settings.VERSION)
    setup_telemetry(app)
    db_manager.create_tables()
    await trading_manager.exchange_connector.connect()
    if settings.AUTO_START_ENGINES:
        await _start_engine("trading", trading_manager.start_trading)
        await _start_engine("sniper", trading_manager.start_sniper)
        logger.info("Motores de trading e Sniper iniciados automaticamente.")
    else:
        logger.info("Motores não iniciados automaticamente; use os endpoints de controle.")
    try:
        yield
    finally:
        logger.info("Desligando motores de trading e sniper...")
        await trading_manager.stop_all()
        await _stop_engine_tasks()
        logger.info("Todos os motores parados com sucesso.")


app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION, lifespan=lifespan)
allowed_origins = [origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(RequestRateLimitMiddleware, settings=settings)


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Remove dados sensíveis antes de retornar um usuário pela API."""
    return {"username": user["username"], "roles": list(user.get("roles", []))}


def _demo_auth_available() -> bool:
    return settings.DEMO_AUTH_ENABLED and settings.ENVIRONMENT.lower() != "production"


def _auth_users() -> Dict[str, Dict[str, Any]]:
    if settings.AUTH_MODE.lower() == "env":
        if not settings.AUTH_USERNAME or not settings.AUTH_PASSWORD:
            return {}
        return {
            settings.AUTH_USERNAME: {
                "username": settings.AUTH_USERNAME,
                "password": settings.AUTH_PASSWORD,
                "roles": ["admin", "trader"],
            }
        }
    return FAKE_USERS_DB if _demo_auth_available() else {}


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    users = _auth_users()
    if not users:
        raise credentials_exception
    username = verify_token(token, credentials_exception)
    user = users.get(username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return current_user


async def get_admin_user(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    if not is_admin(current_user.get("roles", [])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


async def get_trader_user(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    if not is_trader(current_user.get("roles", [])):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


async def _start_engine(name: str, factory) -> bool:
    """Inicia um motor uma única vez e registra sua task para shutdown limpo."""
    current_task = engine_tasks.get(name)
    if current_task and not current_task.done():
        return False
    if not trading_manager.exchange_connector.is_connected:
        await trading_manager.exchange_connector.connect()
    task = asyncio.create_task(factory(), name=f"zia-{name}")
    engine_tasks[name] = task
    return True


async def _stop_engine_tasks() -> None:
    tasks = [task for task in engine_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    engine_tasks.clear()


@app.get("/healthz")
async def healthz() -> Dict[str, Any]:
    """Liveness/readiness sem autenticação; não expõe segredos ou dados de conta."""
    try:
        db_manager.get_account_state("default_account")
        database_persistent = not settings.DATABASE_URL.startswith("sqlite:")
        redis_health = trading_manager.redis_cache.health()
        if settings.REQUIRE_PERSISTENT_DATABASE and not database_persistent:
            raise RuntimeError("PostgreSQL persistente obrigatório")
        if settings.REQUIRE_PERSISTENT_REDIS and not bool(redis_health.get("persistent")):
            raise RuntimeError("Redis persistente obrigatório")
        return {
            "status": "ok",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "exchange_connected": trading_manager.exchange_connector.is_connected,
            "database": {"persistent": database_persistent},
            "redis": redis_health,
            "news_providers": trading_manager.news_processor.health(),
        }
    except Exception as exc:
        logger.error("Falha no healthcheck: %s", exc)
        raise HTTPException(status_code=503, detail="service_unhealthy") from exc


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type="text/plain")


@app.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Dict[str, str]:
    users = _auth_users()
    if not users:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    user = users.get(form_data.username)
    if not user or not secrets.compare_digest(user["password"], form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me")
async def read_users_me(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, Any]:
    return _public_user(current_user)


@app.get("/test_rate_limit")
async def test_rate_limit(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    return {"status": "ok", "user": current_user["username"]}


@app.get("/users/me/items/")
async def read_own_items(
    current_user: Dict[str, Any] = Depends(get_trader_user),
):
    return [{"item_id": "Foo", "owner": current_user["username"]}]


def _runtime_status_payload() -> Dict[str, Any]:
    tasks = {
        name: bool(task and not task.done())
        for name, task in engine_tasks.items()
    }
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engines": tasks,
        "runtime": trading_manager.runtime_status(),
        "exchange": {
            "connected": trading_manager.exchange_connector.is_connected,
            "mode": settings.BINANCE_MODE,
        },
        "redis": trading_manager.redis_cache.health(),
        "news_providers": trading_manager.news_processor.health(),
    }


@app.get("/admin/dashboard")
async def admin_dashboard(
    current_user: Dict[str, Any] = Depends(get_admin_user),
):
    return {"message": f"Welcome, admin {current_user['username']}", "status": _runtime_status_payload()}


@app.post("/admin/kill-switch")
async def admin_kill_switch(
    reason: str = Body(..., embed=True, min_length=3, max_length=200),
    current_user: Dict[str, Any] = Depends(get_admin_user),
):
    return await trading_manager.trigger_kill_switch(reason, actor=current_user["username"])


@app.get("/status")
async def status_alias(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    account = db_manager.get_account_state("default_account")
    positions = db_manager.get_open_positions("default_account")
    daily = db_manager.get_daily_pnl("default_account", datetime.now(timezone.utc).replace(tzinfo=None))
    payload = _runtime_status_payload()
    payload.update({
        "balance": float(account.balance) if account else 0.0,
        "initial_capital": float(account.initial_capital) if account else 0.0,
        "daily_pnl": float(daily.pnl) if daily else 0.0,
        "open_positions": [
            {"symbol": item.symbol, "quantity": float(item.quantity), "entry_price": float(item.entry_price), "current_price": float(item.current_price), "unrealized_pnl": float(item.unrealized_pnl or 0.0)}
            for item in positions
        ],
    })
    return payload


@app.post("/order")
async def create_order(
    order: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    source = str(order.pop("source", "manual")).lower()
    confirmed = bool(order.pop("confirmed", False))
    try:
        return await trading_manager.order_manager.submit(order, source=source, confirmed=confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/order/confirm")
async def confirm_order(
    request: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    token = str(request.get("confirmation_token", ""))
    approved = bool(request.get("approved", True))
    try:
        return await trading_manager.order_manager.confirm(token, approved=approved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/market")
async def market_alias(
    symbol: str,
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    try:
        normalized = trading_manager.market_connector.normalize_symbol(symbol)
        market_data = await trading_manager.market_connector.get_market_data(normalized)
        order_book = await trading_manager.market_connector.get_order_book(normalized, limit=20)
        return {"symbol": normalized, "market": market_data, "order_book": order_book}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dados de mercado indisponíveis") from exc


@app.get("/logs")
async def logs_alias(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    logs = [item for item in db_manager.get_system_logs("default_account") if item.timestamp and item.timestamp >= cutoff]
    return {"since": cutoff.isoformat(), "logs": [{"timestamp": item.timestamp.isoformat(), "level": item.level, "module": item.module, "message": item.message} for item in logs]}


@app.get("/dashboard/status")
async def dashboard_status(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    return _runtime_status_payload()


@app.get("/core/analyze")
async def analyze_core_symbol(
    symbol: str,
    offline: bool = False,
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    """Executa leitura explicável de mercado sem enviar ordem."""
    try:
        return await trading_manager.command_manager.analyze_symbol(symbol, offline=offline)
    except Exception as exc:
        logger.warning("Falha na análise do core para %s: %s", symbol, exc)
        raise HTTPException(status_code=503, detail="análise indisponível no momento") from exc


@app.post("/core/sync")
async def sync_core_data(
    request: Dict[str, Any] = Body(default_factory=dict),
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    """Sincroniza feeds e retorna snapshots; não executa ordens."""
    raw_symbols = request.get("symbols") or settings.SYMBOLS
    symbols = [raw_symbols] if isinstance(raw_symbols, str) else raw_symbols
    try:
        return await trading_manager.command_manager.sync_market(
            symbols=symbols,
            limit=int(request.get("limit", 250)),
            offline=bool(request.get("offline", False)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Falha na sincronização do core: %s", exc)
        raise HTTPException(status_code=503, detail="sincronização indisponível no momento") from exc


@app.get("/api/optimize_sharpe")
async def optimize_sharpe(
    asset_list: str,
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    requested_assets = [value.strip() for value in asset_list.split(",") if value.strip()]
    if not requested_assets:
        raise HTTPException(status_code=400, detail="asset_list não pode ser vazio")
    symbol = requested_assets[0]
    try:
        historical_data = await trading_manager.exchange_connector.get_historical_data(
            symbol,
            settings.TIMEFRAME,
            limit=min(8760, 10000),
        )
        optimizer = StrategyOptimizer(
            settings,
            trading_manager.backtest_engine.db_manager,
            budget=OptimizationBudget(
                max_evaluations=settings.OPTIMIZER_MAX_EVALUATIONS,
                max_seconds=settings.OPTIMIZER_MAX_SECONDS,
                validation_fraction=settings.OPTIMIZER_VALIDATION_FRACTION,
                min_trades=settings.OPTIMIZER_MIN_TRADES,
            ),
        )
        recommendation = await optimizer.optimize_async(symbol, historical_data, strategy_name="API Sharpe Optimization")
        return {
            "requested_assets": requested_assets,
            "optimized_asset": symbol,
            "orders_sent": 0,
            "recommendation": recommendation,
        }
    except Exception as exc:
        logger.exception("Falha na otimização Sharpe para %s", symbol)
        raise HTTPException(status_code=503, detail="otimização indisponível no momento") from exc


@app.post("/runtime/reload")
async def reload_runtime(
    current_user: Dict[str, Any] = Depends(get_admin_user),
) -> Dict[str, Any]:
    profile = trading_manager.reload_runtime_config()
    return {"reloaded": True, "profile": profile, "status": _runtime_status_payload()}


@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token")
    try:
        if not token:
            raise HTTPException(status_code=401, detail="Token obrigatório")
        username = verify_token(token, HTTPException(status_code=401, detail="Token inválido"))
        user = _auth_users().get(username)
        if not user or not is_trader(user.get("roles", [])):
            raise HTTPException(status_code=403, detail="Permissão insuficiente")
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_runtime_status_payload())
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@app.get("/")
async def root_rate_limited(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, str]:
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.post("/trading/start")
async def start_trading(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    started = await _start_engine("trading", trading_manager.start_trading)
    return {"message": "Motor de Trading iniciado." if started else "Motor de Trading já estava em execução.", "started": started}


@app.post("/sniper/start")
async def start_sniper(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    started = await _start_engine("sniper", trading_manager.start_sniper)
    return {"message": "Motor Sniper iniciado." if started else "Motor Sniper já estava em execução.", "started": started}


@app.post("/trading/stop")
async def stop_trading(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, str]:
    await trading_manager.stop_all()
    await _stop_engine_tasks()
    return {"message": "Todos os motores parados."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.API_PORT)
