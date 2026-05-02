import asyncio
import logging
from config.settings import Settings
from core.manager import TradingManager
from data.news_processor import NewsProcessor
from database import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    settings = Settings()
    logger.info(f"Iniciando ZIA Trader v{settings.VERSION} - {settings.PROJECT_NAME}")

    # Inicializar banco de dados
    init_db()

    # Inicializar processador de notícias
    news_processor = NewsProcessor(settings)

    # Inicializar o gerenciador de trading
    trading_manager = TradingManager(settings)

    try:
        await trading_manager.start_trading() # Ou start_sniper, ou run_backtest dependendo do modo
        # Manter o evento loop rodando
        while True:
            await asyncio.sleep(settings.TRADING_LOOP_INTERVAL) # Usa o intervalo configurado
    except asyncio.CancelledError:
        logger.info("Execução do ZIA Trader cancelada.")
    except Exception as e:
        logger.error(f"Erro crítico no ZIA Trader: {e}")
    finally:
        await trading_manager.stop_all()
        logger.info("ZIA Trader finalizado.")

if __name__ == "__main__":
    asyncio.run(main())
