"""Adaptador para MetaTrader 5 (MT5).
Requer a biblioteca 'MetaTrader5' e ambiente Windows/Wine para execução live.
A arquitetura está refinada para integração assíncrona com o core.
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
from config.settings import Settings
from execution.live_authorization import live_submission_block_reason

logger = logging.getLogger(__name__)

class MetaTrader5Adapter:
    """Adaptador refinado para MT5, suportando B3 e Forex."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.is_connected = False
        self._mt5 = None

    async def connect(self) -> None:
        """Inicializa a conexão com o terminal MT5."""
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
            if not mt5.initialize():
                logger.error("Falha ao inicializar MT5: %s", mt5.last_error())
                self.is_connected = False
                return
            self.is_connected = True
            logger.info("Conectado ao terminal MetaTrader 5.")
        except ImportError:
            logger.warning("Biblioteca MetaTrader5 não instalada. Operando em modo stub.")
            self.is_connected = False

    async def close(self) -> None:
        if self._mt5:
            self._mt5.shutdown()
        self.is_connected = False

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """Busca dados históricos do MT5."""
        if not self.is_connected or not self._mt5:
            raise RuntimeError("MT5 não conectado")
        
        # Mapeamento de timeframe para constantes MT5
        tf_map = {
            "1m": self._mt5.TIMEFRAME_M1,
            "5m": self._mt5.TIMEFRAME_M5,
            "15m": self._mt5.TIMEFRAME_M15,
            "1h": self._mt5.TIMEFRAME_H1,
            "1d": self._mt5.TIMEFRAME_D1,
        }
        mt5_tf = tf_map.get(timeframe, self._mt5.TIMEFRAME_H1)
        
        rates = self._mt5.copy_rates_from_pos(symbol, mt5_tf, 0, limit)
        if rates is None:
            raise RuntimeError(f"Falha ao obter dados para {symbol}: {self._mt5.last_error()}")
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df.set_index('time')

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        if not self.is_connected or not self._mt5:
            return {"symbol": symbol, "last": 0.0, "error": "MT5_DISCONNECTED"}
            
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"symbol": symbol, "last": 0.0, "error": "SYMBOL_NOT_FOUND"}
        tick_time = getattr(tick, "time_msc", None)
        divisor = 1000.0
        if tick_time is None:
            tick_time = getattr(tick, "time", None)
            divisor = 1.0
        try:
            quote_timestamp = datetime.fromtimestamp(float(tick_time) / divisor, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            quote_timestamp = None

        return {
            "symbol": symbol,
            "last": tick.last,
            "bid": tick.bid,
            "ask": tick.ask,
            "volume": tick.volume,
            "timestamp": quote_timestamp,
            "timestamp_source": "exchange_tick",
        }

    async def place_order(
        self,
        symbol: str,
        action: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executa ordens via MT5 com proteção fail-closed."""
        authorization_error = live_submission_block_reason(self.settings)
        if authorization_error:
            raise RuntimeError(f"MT5 live bloqueado: {authorization_error}")
        raise RuntimeError(
            "MT5 live desabilitado: client_order_id e reconciliação remota não estão homologados"
        )

    async def get_account_balance(self) -> Dict[str, float]:
        if not self.is_connected or not self._mt5:
            return {}
        info = self._mt5.account_info()
        return {"balance": info.balance, "equity": info.equity, "margin": info.margin}
