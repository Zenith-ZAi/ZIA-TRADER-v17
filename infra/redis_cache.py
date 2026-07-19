import redis
import json
from typing import Any, Optional
from config.settings import settings

class RedisCache:
    """Gerenciador de cache Redis para estado em tempo real."""
    def __init__(self):
        self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    def set_state(self, key: str, value: Any, expire: int = 3600):
        """Armazena um estado serializado em JSON."""
        self.client.set(key, json.dumps(value), ex=expire)

    def get_state(self, key: str) -> Optional[Any]:
        """Recupera um estado e desserializa do JSON."""
        data = self.client.get(key)
        return json.loads(data) if data else None

    def update_price(self, symbol: str, price: float):
        """Atualiza o preço atual de um ativo."""
        self.client.hset("current_prices", symbol, price)

    def get_price(self, symbol: str) -> float:
        """Recupera o último preço conhecido de um ativo."""
        price = self.client.hget("current_prices", symbol)
        return float(price) if price else 0.0

redis_cache = RedisCache()
