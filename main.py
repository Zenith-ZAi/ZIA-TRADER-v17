import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from typing import Dict, Any
from config.settings import settings
from core.engine import trading_engine
from core.sniper_engine import sniper_engine
from monitoring.metrics import metrics_collector

app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)

@app.on_event("startup")
async def startup_event():
    """Inicializa os motores de trading e sniper em segundo plano."""
    print(f"Iniciando {settings.PROJECT_NAME} v{settings.VERSION}...")
    # Inicia os motores de trading e sniper como tarefas assíncronas
    asyncio.create_task(trading_engine.start())
    asyncio.create_task(sniper_engine.start())
    print("Motores de Trading e Sniper iniciados com sucesso.")

@app.on_event("shutdown")
async def shutdown_event():
    """Para os motores de trading e sniper ao desligar a aplicação."""
    print("Desligando motores de trading e sniper...")
    trading_engine.stop()
    sniper_engine.stop()
    print("Motores parados com sucesso.")

@app.get("/")
async def root():
    """Endpoint raiz para verificação de status básico."""
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "health": metrics_collector.check_health()
    }

@app.get("/metrics")
async def get_metrics():
    """Endpoint para visualização de métricas de performance."""
    return metrics_collector.get_summary()

@app.post("/trading/start")
async def start_trading():
    """Endpoint para iniciar o motor de trading manualmente."""
    if not trading_engine.is_running:
        asyncio.create_task(trading_engine.start())
        return {"message": "Motor de Trading iniciado."}
    return {"message": "Motor de Trading já está em execução."}

@app.post("/trading/stop")
async def stop_trading():
    """Endpoint para parar o motor de trading manualmente."""
    if trading_engine.is_running:
        trading_engine.stop()
        return {"message": "Motor de Trading parado."}
    return {"message": "Motor de Trading já está parado."}

if __name__ == "__main__":
    # Executa a aplicação FastAPI usando Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.API_PORT)
