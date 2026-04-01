import json
import asyncio
from aiokafka import AIOKafkaProducer
from config.settings import settings
from infra.redis_cache import redis_cache

class MarketDataProducer:
    """Produtor Kafka para dados de mercado em tempo real."""
    def __init__(self):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )

    async def start(self):
        """Inicia o produtor Kafka."""
        await self.producer.start()

    async def stop(self):
        """Para o produtor Kafka."""
        await self.producer.stop()

    async def send_market_data(self, symbol: str, data: dict):
        """Envia dados de mercado para o tópico Kafka e atualiza o cache Redis."""
        # Atualiza o cache Redis para acesso rápido
        if 'price' in data:
            redis_cache.update_price(symbol, data['price'])
        
        # Envia para o Kafka para processamento assíncrono
        await self.producer.send_and_wait(settings.KAFKA_TOPIC_MARKET_DATA, data)

market_producer = MarketDataProducer()
