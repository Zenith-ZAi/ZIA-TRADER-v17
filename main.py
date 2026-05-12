"""
main.py — ZIA TRADER v17
Ponto de entrada principal: inicia o motor de trading
e o servidor FastAPI com o agente de chat ao vivo.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import Settings
from core.manager import TradingManager
from data.news_processor import NewsProcessor
from database import init_db
from agent.chat_router import router as agent_router, session_manager
from fastapi import Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

settings = Settings()

# ─── Lifespan: inicializa tudo antes de aceitar requests ─────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown do sistema completo."""

    logger.info(f"🚀 Iniciando {settings.PROJECT_NAME} v{settings.VERSION}")

    # 1. Banco de dados
    await init_db()
    logger.info("✅ Banco de dados inicializado")

    # 2. TradingManager
    trading_manager = TradingManager(settings)
    app.state.trading_manager = trading_manager
    logger.info("✅ TradingManager criado")

    # 3. Injeta TradingManager nas sessões do agente
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    session_manager.get_or_create("default", api_key, trading_manager, settings)
    if api_key:
        logger.info("Agente ZIA inicializado com TradingManager")
    else:
        logger.warning("ANTHROPIC_API_KEY não configurada — agente rodará sem IA")

    # 4. Inicia motor de trading em background
    trading_task = asyncio.create_task(trading_manager.start_trading())
    logger.info("✅ Motor de trading iniciado em background")

    yield  # Servidor FastAPI aceita requests aqui

    # Shutdown
    logger.info("⏹  Encerrando ZIA TRADER...")
    trading_task.cancel()
    try:
        await trading_task
    except asyncio.CancelledError:
        pass
    await trading_manager.stop_all()
    logger.info("✅ Sistema encerrado com segurança.")


# ─── App FastAPI ──────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="ZIA TRADER — Sistema de Trading Autônomo com IA",
    lifespan=lifespan
)

# CORS — permite frontend conectar
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Em produção: substitua pelo domínio real
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas do Agente
app.include_router(agent_router)

@app.get("/health")
async def health():
    return {
        "status": "online",
        "version": settings.VERSION,
        "project": settings.PROJECT_NAME
    }

@app.get("/learning/status")
async def learning_status(request: Request):
    """Retorna o relatório do último ciclo de aprendizado adaptativo."""
    manager = getattr(request.app.state, "trading_manager", None)
    if manager and hasattr(manager, "adaptive_trainer"):
        report = manager.adaptive_trainer.get_last_report()
        return {"status": "ok", "last_report": report, "cycle_count": manager.adaptive_trainer._cycle_count}
    return {"status": "unavailable", "reason": "TradingManager não inicializado"}

@app.post("/learning/trigger")
async def trigger_learning(request: Request):
    """Força um ciclo de aprendizado imediato (para testes e ajuste manual)."""
    manager = getattr(request.app.state, "trading_manager", None)
    if manager and hasattr(manager, "adaptive_trainer"):
        import asyncio
        asyncio.create_task(manager.adaptive_trainer.run_cycle())
        return {"status": "triggered", "message": "Ciclo de aprendizado iniciado em background."}
    return {"status": "error", "reason": "AdaptiveTrainer não disponível"}

@app.get("/")
async def root():
    return {
        "message": f"Bem-vindo ao {settings.PROJECT_NAME} v{settings.VERSION}",
        "docs": "/docs",
        "agent_chat": "/agent/chat",
        "agent_ws":   "/agent/ws/{session_id}"
    }

# ─── Entrada direta ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        reload=False,
        log_level="info"
    )
