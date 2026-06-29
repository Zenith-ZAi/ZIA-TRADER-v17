import asyncio
import time
from collections import defaultdict
from typing import Dict

class RateLimiter:
    """Implementa um limitador de taxa simples baseado em tokens ou tempo."""
    def __init__(self, rate_limit: int, interval: int):
        self.rate_limit = rate_limit  # Número máximo de requisições
        self.interval = interval      # Intervalo de tempo em segundos
        self.clients: Dict[str, list] = defaultdict(list) # {client_id: [timestamps]}

    async def __call__(self, client_id: str):
        now = time.time()
        # Remove timestamps antigos
        self.clients[client_id] = [t for t in self.clients[client_id] if t > now - self.interval]

        if len(self.clients[client_id]) >= self.rate_limit:
            # Calcular tempo de espera até que a próxima requisição seja permitida
            wait_time = self.clients[client_id][0] + self.interval - now
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            # Após a espera, re-verificar e ajustar
            now = time.time()
            self.clients[client_id] = [t for t in self.clients[client_id] if t > now - self.interval]
            if len(self.clients[client_id]) >= self.rate_limit:
                # Se ainda exceder, significa que o intervalo de espera não foi suficiente
                # Isso pode acontecer se o rate_limit for muito baixo ou o intervalo muito curto
                # Para simplificar, vamos apenas adicionar o timestamp e permitir, mas em um sistema real
                # poderíamos lançar uma exceção ou ter uma política de retry mais sofisticada.
                pass

        self.clients[client_id].append(now)

# Exemplo de uso:
# rate_limiter = RateLimiter(rate_limit=5, interval=10) # 5 requisições a cada 10 segundos
# async def some_api_call(client_id):
#     await rate_limiter(client_id)
#     print(f"Requisição de {client_id} processada.")
