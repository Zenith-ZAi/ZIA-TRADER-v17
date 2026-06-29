import redis
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

class RedisCache:
    def __init__(self, redis_url: str):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        logger.info(f"RedisCache inicializado com URL: {redis_url}")

    async def set_state(self, key: str, value: Any, expire: Optional[int] = None):
        try:
            if isinstance(value, dict) or isinstance(value, list):
                value = json.dumps(value)
            self.redis_client.set(key, value)
            if expire:
                self.redis_client.expire(key, expire)
        except Exception as e:
            logger.error(f"Erro ao definir estado no Redis para a chave {key}: {e}")

    async def get_state(self, key: str) -> Optional[Any]:
        try:
            value = self.redis_client.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value # Retorna como string se não for JSON
            return None
        except Exception as e:
            logger.error(f"Erro ao obter estado do Redis para a chave {key}: {e}")
            return None

    async def delete_state(self, key: str):
        try:
            self.redis_client.delete(key)
        except Exception as e:
            logger.error(f"Erro ao deletar estado do Redis para a chave {key}: {e}")
