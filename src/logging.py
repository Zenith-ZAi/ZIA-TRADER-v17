"""
Sistema de logging avançado para RoboTrader
"""

import os
import sys
from pathlib import Path
from typing import Optional
from loguru import logger

# Importar config.py para acessar as configurações de logging
# Certifique-se de que config.py está no PYTHONPATH ou no mesmo diretório
try:
    from config import config
except ImportError:
    # Fallback para configurações padrão se config.py não for encontrado
    class DefaultLoggingConfig:
        level = "INFO"
        file = "logs/robotrader.log"
        format = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
        max_size = "10 MB"
        retention = "10 days"
    
    class DefaultConfig:
        logging = DefaultLoggingConfig()
    
    config = DefaultConfig()
    logger.warning("Não foi possível carregar config.py. Usando configurações de logging padrão.")

def setup_logging(name: Optional[str] = None) -> object:
    """
    Configura o sistema de logging usando loguru.
    
    Args:
        name: Nome do logger (opcional).
        
    Returns:
        Instância do logger configurado.
    """
    
    # Remover handlers padrão para evitar duplicação
    logger.remove()
    
    log_dir = Path(config.logging.file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configurar handler para console (stdout)
    logger.add(
        sys.stdout,
        level=config.logging.level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True,
        enqueue=True  # Thread-safe
    )
    
    # Configurar handler para arquivo de log principal
    logger.add(
        config.logging.file,
        level=config.logging.level,
        format=config.logging.format,
        rotation=config.logging.max_size,
        retention=config.logging.retention,
        compression="zip",
        enqueue=True,  # Thread-safe
        backtrace=True,
        diagnose=True
    )
    
    # Configurar handler para erros críticos (arquivo separado)
    logger.add(
        log_dir / "errors.log",
        level="ERROR",
        format=config.logging.format,
        rotation="1 week",
        retention="1 month",
        compression="zip",
        enqueue=True
    )
    
    # Configurar handler para logs de trading (arquivo separado)
    logger.add(
        log_dir / "trading.log",
        level="INFO",
        format=config.logging.format,
        filter=lambda record: "trading" in record["extra"], # Filtra logs com 'trading' no extra
        rotation="1 day",
        retention="3 months",
        compression="zip",
        enqueue=True
    )
    
    if name:
        return logger.bind(name=name)
    
    return logger


def get_logger(name: str) -> object:
    """
    Obtém um logger com nome específico.
    
    Args:
        name: Nome do logger.
        
    Returns:
        Instância do logger.
    """
    return logger.bind(name=name)


def log_trade(symbol: str, action: str, amount: float, price: float, **kwargs):
    """
    Log específico para operações de trading.
    
    Args:
        symbol: Símbolo do ativo.
        action: Ação (buy/sell/hold).
        amount: Quantidade.
        price: Preço.
        **kwargs: Dados adicionais.
    """
    trade_logger = logger.bind(trading=True)
    trade_logger.info(
        f"TRADE | {symbol} | {action.upper()} | Amount: {amount} | Price: {price} | {kwargs}"
    )


def log_performance(symbol: str, pnl: float, roi: float, **kwargs):
    """
    Log específico para performance.
    
    Args:
        symbol: Símbolo do ativo.
        pnl: Profit and Loss.
        roi: Return on Investment.
        **kwargs: Dados adicionais.
    """
    perf_logger = logger.bind(performance=True)
    perf_logger.info(
        f"PERFORMANCE | {symbol} | PnL: {pnl:.4f} | ROI: {roi:.2f}% | {kwargs}"
    )


def log_error_with_context(error: Exception, context: dict):
    """
    Log de erro com contexto adicional.
    
    Args:
        error: Exceção capturada.
        context: Contexto adicional.
    """
    logger.error(
        f"Error: {str(error)} | Context: {context}",
        exc_info=True
    )



