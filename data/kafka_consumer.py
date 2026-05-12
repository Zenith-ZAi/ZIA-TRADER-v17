import json
import logging

from config.settings import settings

logger = logging.getLogger(__name__)


class MarketDataConsumer:
    """Consumidor Kafka para processamento de dados de mercado."""

    def __init__(self):
        self._consumer = None

    async def start(self):
        """Inicia o consumidor Kafka."""
        try:
            from aiokafka import AIOKafkaConsumer

            self._consumer = AIOKafkaConsumer(
                settings.KAFKA_TOPIC_MARKET_DATA,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="zia_market_data_group",
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            )
            await self._consumer.start()
            logger.info("Kafka consumer started.")
        except Exception as e:
            logger.warning("Kafka consumer unavailable: %s", e)

    async def stop(self):
        if self._consumer:
            await self._consumer.stop()

    async def consume_market_data(self, callback):
        if not self._consumer:
            logger.warning("Kafka consumer not started.")
            return
        try:
            async for msg in self._consumer:
                data = msg.value
                await callback(data)
        except Exception as e:
            logger.error("Erro ao consumir dados de mercado: %s", e)
