import json
import asyncio
from aiokafka import AIOKafkaConsumer
from config.settings import settings

class MarketDataConsumer:
    """Consumidor Kafka para processamento de dados de mercado."""
    def __init__(self):
        self.consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC_MARKET_DATA,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="zia_market_data_group",
            value_deserializer=lambda v: json.loads(v.decode('utf-8'))
        )

    async def start(self):
        """Inicia o consumidor Kafka."""
        await self.consumer.start()

    async def stop(self):
        """Para o consumidor Kafka."""
        await self.consumer.stop()

    async def consume_market_data(self, callback):
        """Consome dados de mercado e executa um callback para cada mensagem."""
        try:
            async for msg in self.consumer:
                data = msg.value
                await callback(data)
        except Exception as e:
            print(f"Erro ao consumir dados de mercado: {e}")

market_consumer = MarketDataConsumer()
