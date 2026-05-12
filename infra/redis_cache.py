import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RedisCache:
    """Gerenciador de cache Redis para estado em tempo real.

    Falls back to an in-memory dict when Redis is unavailable so the
    application can still run in development without a Redis server.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._redis_url = redis_url
        self._client = None
        self._fallback: dict = {}
        self._connected = False
        self._try_connect()

    def _try_connect(self) -> None:
        try:
            import redis as _redis

            self._client = _redis.from_url(self._redis_url, decode_responses=True)
            self._client.ping()
            self._connected = True
            logger.info("Redis connected at %s", self._redis_url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — using in-memory fallback.", exc)
            self._client = None
            self._connected = False

    # ------------------------------------------------------------------
    # Public API — all methods are sync-safe so callers may optionally
    # ``await`` them (Python silently ignores ``await`` on non-coroutines
    # when wrapped; callers were updated to NOT await these).
    # ------------------------------------------------------------------

    def set_state(self, key: str, value: Any, expire: int = 3600) -> None:
        if self._connected and self._client:
            try:
                self._client.set(key, json.dumps(value), ex=expire)
                return
            except Exception:
                pass
        self._fallback[key] = value

    def get_state(self, key: str) -> Optional[Any]:
        if self._connected and self._client:
            try:
                data = self._client.get(key)
                return json.loads(data) if data else None
            except Exception:
                pass
        return self._fallback.get(key)

    def update_price(self, symbol: str, price: float) -> None:
        if self._connected and self._client:
            try:
                self._client.hset("current_prices", symbol, price)
                return
            except Exception:
                pass
        self._fallback.setdefault("current_prices", {})[symbol] = price

    def get_price(self, symbol: str) -> float:
        if self._connected and self._client:
            try:
                price = self._client.hget("current_prices", symbol)
                return float(price) if price else 0.0
            except Exception:
                pass
        prices = self._fallback.get("current_prices", {})
        val = prices.get(symbol)
        return float(val) if val else 0.0
