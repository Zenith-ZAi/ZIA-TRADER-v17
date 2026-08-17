import asyncio
from contextlib import asynccontextmanager
import logging
import secrets
from datetime import timedelta
from typing import Any, Dict

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from prometheus_client import generate_latest

from config.settings import settings
from core.manager import TradingManager
from database_manager import DatabaseManager
from monitoring.telemetry.telemetry_setup import setup_telemetry
from security.jwt_utils import create_access_token, verify_token
from security.rbac_utils import is_admin, is_trader
from security.rate_limiter import RateLimiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


db_manager = DatabaseManager(settings.DATABASE_URL)
db_manager.create_tables()
rate_limiter = RateLimiter(
    rate_limit=settings.API_RATE_LIMIT,
    interval=settings.API_RATE_LIMIT_INTERVAL,
)
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


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Remove dados sensíveis antes de retornar um usuário pela API."""
    return {"username": user["username"], "roles": list(user.get("roles", []))}


def _demo_auth_available() -> bool:
    return settings.DEMO_AUTH_ENABLED and settings.ENVIRONMENT.lower() != "production"


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not _demo_auth_available():
        raise credentials_exception
    username = verify_token(token, credentials_exception)
    user = FAKE_USERS_DB.get(username)
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


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type="text/plain")


@app.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Dict[str, str]:
    if not _demo_auth_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo authentication is disabled; configure the user service.",
        )
    user = FAKE_USERS_DB.get(form_data.username)
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


@app.get("/users/me/items/")
async def read_own_items(
    current_user: Dict[str, Any] = Depends(get_trader_user),
):
    return [{"item_id": "Foo", "owner": current_user["username"]}]


@app.get("/admin/dashboard")
async def admin_dashboard(
    current_user: Dict[str, Any] = Depends(get_admin_user),
):
    return {"message": f"Welcome, admin {current_user['username']}"}


@app.get("/")
async def root_rate_limited(
    current_user: Dict[str, Any] = Depends(get_current_active_user),
) -> Dict[str, str]:
    await rate_limiter(current_user["username"])
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.post("/trading/start")
async def start_trading(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    await rate_limiter(current_user["username"])
    started = await _start_engine("trading", trading_manager.start_trading)
    return {"message": "Motor de Trading iniciado." if started else "Motor de Trading já estava em execução.", "started": started}


@app.post("/sniper/start")
async def start_sniper(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, Any]:
    await rate_limiter(current_user["username"])
    started = await _start_engine("sniper", trading_manager.start_sniper)
    return {"message": "Motor Sniper iniciado." if started else "Motor Sniper já estava em execução.", "started": started}


@app.post("/trading/stop")
async def stop_trading(
    current_user: Dict[str, Any] = Depends(get_trader_user),
) -> Dict[str, str]:
    await rate_limiter(current_user["username"])
    await trading_manager.stop_all()
    await _stop_engine_tasks()
    return {"message": "Todos os motores parados."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.API_PORT)
