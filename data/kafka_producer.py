import json
import logging

from config.settings import settings

logger = logging.getLogger(__name__)


class MarketDataProducer:
    """Produtor Kafka para dados de mercado em tempo real."""

    def __init__(self, redis_cache=None):
        self._producer = None
        self._redis_cache = redis_cache

    async def start(self):
        try:
            from aiokafka import AIOKafkaProducer

            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()
            logger.info("Kafka producer started.")
        except Exception as e:
            logger.warning("Kafka producer unavailable: %s", e)

    async def stop(self):
        if self._producer:
            await self._producer.stop()

    async def send_market_data(self, symbol: str, data: dict):
        if self._redis_cache and "price" in data:
            self._redis_cache.update_price(symbol, data["price"])

        if self._producer:
            await self._producer.send_and_wait(
                settings.KAFKA_TOPIC_MARKET_DATA, data
            )
