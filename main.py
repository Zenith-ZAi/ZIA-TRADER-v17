import asyncio
import logging
from config.settings import Settings
from core.engine import RoboTraderUnified
from data.news_processor import NewsProcessor
from database import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    settings = Settings()
    logger.info(f"Iniciando ZIA Trader v{settings.VERSION} - {settings.PROJECT_NAME}")

    # Inicializar banco de dados
    await init_db(settings.DATABASE_URL)

    # Inicializar processador de notícias
    news_processor = NewsProcessor(settings)

    # Inicializar o motor de trading unificado
    trader = RoboTraderUnified(settings, news_processor)

    try:
        await trader.start()
        # Manter o evento loop rodando
        while True:
            await asyncio.sleep(3600) # Dorme por 1 hora para manter o bot ativo
    except asyncio.CancelledError:
        logger.info("Execução do ZIA Trader cancelada.")
    except Exception as e:
        logger.error(f"Erro crítico no ZIA Trader: {e}")
    finally:
        await trader.stop()
        await news_processor.close()
        logger.info("ZIA Trader finalizado.")

if __name__ == "__main__":
    asyncio.run(main())
