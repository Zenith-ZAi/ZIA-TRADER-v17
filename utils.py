import logging
import sys
from datetime import datetime

def get_logger(name: str):
    """Configura um logger padrão para o sistema."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

logger = get_logger("ZIA-TRADER")

def format_currency(value: float) -> str:
    return f"${value:,.2f}"

def get_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
