import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class _InMemoryFallback:
    """Simple in-memory key/value store used when Redis is unavailable."""

    def __init__(self):
        self._store: dict = {}
        self._expiry: dict = {}

    def set(self, key: str, value: str):
        self._store[key] = value

    def expire(self, key: str, seconds: int):
        self._expiry[key] = time.time() + seconds

    def get(self, key: str) -> Optional[str]:
        exp = self._expiry.get(key)
        if exp is not None and time.time() > exp:
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return None
        return self._store.get(key)

    def delete(self, key: str):
        self._store.pop(key, None)
        self._expiry.pop(key, None)


class RedisCache:
    def __init__(self, redis_url: str):
        self.redis_client = None
        try:
            import redis as redis_lib
            client = redis_lib.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            # Eagerly probe the connection so we know immediately if Redis is reachable
            client.ping()
            self.redis_client = client
            logger.info(f"RedisCache conectado ao Redis: {redis_url}")
        except Exception as e:
            logger.warning(
                f"Redis não disponível ({e}). Usando cache em memória como fallback."
            )
            self.redis_client = _InMemoryFallback()

    @property
    def is_persistent(self) -> bool:
        """Indica se o estado sobrevive ao reinício do processo."""
        return not isinstance(self.redis_client, _InMemoryFallback)

    def health(self) -> dict[str, object]:
        return {
            "persistent": self.is_persistent,
            "backend": "redis" if self.is_persistent else "memory_fallback",
        }

    async def set_state(self, key: str, value: Any, expire: Optional[int] = None):
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            self.redis_client.set(key, value)
            if expire:
                self.redis_client.expire(key, expire)
        except Exception as e:
            logger.error(f"Erro ao definir estado para a chave {key}: {e}")

    async def get_state(self, key: str) -> Optional[Any]:
        try:
            value = self.redis_client.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except Exception as e:
            logger.error(f"Erro ao obter estado para a chave {key}: {e}")
            return None

    async def delete_state(self, key: str):
        try:
            self.redis_client.delete(key)
        except Exception as e:
            logger.error(f"Erro ao deletar estado para a chave {key}: {e}")
