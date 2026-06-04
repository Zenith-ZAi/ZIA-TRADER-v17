import asyncio
import uvicorn
import logging
from fastapi import FastAPI, HTTPException
from typing import Dict, Any
from config.settings import settings
from core.manager import TradingManager

# Configuração de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

# Inicialização do TradingManager
trading_manager = TradingManager(settings)

@app.on_event("startup")
async def startup_event():
    """Inicializa os motores de trading e sniper em segundo plano."""
    logger.info(f"Iniciando {settings.PROJECT_NAME} v{settings.VERSION}...")
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
async def root():
    """Endpoint raiz para verificação de status básico."""
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running"
    }

@app.post("/trading/start")
async def start_trading():
    """Endpoint para iniciar o motor de trading manualmente."""
    asyncio.create_task(trading_manager.start_trading())
    return {"message": "Motor de Trading iniciado."}

@app.post("/trading/stop")
async def stop_trading():
    """Endpoint para parar o motor de trading manualmente."""
    await trading_manager.stop_all()
    return {"message": "Todos os motores parados."}

if __name__ == "__main__":
    # Executa a aplicação FastAPI usando Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
