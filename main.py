import asyncio
import uvicorn
import logging
from fastapi import FastAPI, HTTPException, Depends, status, Response
from prometheus_client import generate_latest
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from security.jwt_utils import create_access_token, verify_token
from security.rbac_utils import has_permission, is_admin, is_trader
from security.rate_limiter import RateLimiter
from datetime import timedelta
from typing import Dict, Any, List
from config.settings import settings
from core.manager import TradingManager
from database_manager import DatabaseManager
from monitoring.telemetry.telemetry_setup import setup_telemetry

db_manager = DatabaseManager(settings.DATABASE_URL)

# Inicialização do Rate Limiter
rate_limiter = RateLimiter(rate_limit=settings.API_RATE_LIMIT, interval=settings.API_RATE_LIMIT_INTERVAL)

# OAuth2PasswordBearer para autenticação JWT
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Usuários mock para demonstração (em produção, viriam do banco de dados)
FAKE_USERS_DB = {
    "user": {"username": "user", "password": "password", "roles": ["trader"]},
    "admin": {"username": "admin", "password": "admin", "roles": ["admin", "trader"]},
}

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    username = verify_token(token, credentials_exception)
    user = FAKE_USERS_DB.get(username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: Dict = Depends(get_current_user)):
    # Aqui você pode adicionar lógica para verificar se o usuário está ativo, etc.
    return current_user

async def get_admin_user(current_user: Dict = Depends(get_current_active_user)):
    if not is_admin(current_user["roles"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return current_user

async def get_trader_user(current_user: Dict = Depends(get_current_active_user)):
    if not is_trader(current_user["roles"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return current_user

# Configuração de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = FAKE_USERS_DB.get(form_data.username)
    if not user or user["password"] != form_data.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me")
async def read_users_me(current_user: Dict = Depends(get_current_active_user)):
    return current_user

@app.get("/users/me/items/")
async def read_own_items(current_user: Dict = Depends(get_trader_user)):
    return [{"item_id": "Foo", "owner": current_user["username"]}]

@app.get("/admin/dashboard")
async def admin_dashboard(current_user: Dict = Depends(get_admin_user)):
    return {"message": f"Welcome, admin {current_user["username"]}"}

# Inicialização do TradingManager
trading_manager = TradingManager(settings, db_manager)

@app.on_event("startup")
async def startup_event():
    """Inicializa os motores de trading e sniper em segundo plano."""
    logger.info(f"Iniciando {settings.PROJECT_NAME} v{settings.VERSION}...")
    setup_telemetry(app)
    # Inicializa as tabelas do banco de dados
    db_manager.create_tables()
    # Inicia os motores via TradingManager
    asyncio.create_task(trading_manager.start_trading())
    asyncio.create_task(trading_manager.start_sniper())
    logger.info("Motores de Trading e Sniper iniciados com sucesso via TradingManager.")

@app.on_event("shutdown")
async def shutdown_event():
    """Para os motores de trading e sniper ao desligar a aplicação."""
    logger.info("Desligando motores de trading e sniper...")
    await trading_manager.stop_all()
    logger.info("Todos os motores parados com sucesso.")

@app.get("/")
async def root_rate_limited(current_user: Dict = Depends(get_current_active_user)):
    await rate_limiter(current_user["username"])
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running"
    }


@app.post("/trading/start")
async def start_trading(current_user: Dict = Depends(get_trader_user)):
    await rate_limiter(current_user["username"])
    asyncio.create_task(trading_manager.start_trading())
    return {"message": "Motor de Trading iniciado."}

@app.post("/trading/stop")
async def stop_trading(current_user: Dict = Depends(get_trader_user)):
    await rate_limiter(current_user["username"])
    await trading_manager.stop_all()
    return {"message": "Todos os motores parados."}

if __name__ == "__main__":
    # Executa a aplicação FastAPI usando Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
