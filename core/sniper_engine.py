import asyncio
from typing import List, Dict, Any
from config.settings import settings
from infra.redis_cache import redis_cache
from execution.execution_engine import execution_engine

class SniperEngine:
    """Motor Sniper para execução rápida em eventos de alta volatilidade."""
    def __init__(self):
        self.is_running = False
        self.symbols = settings.SYMBOLS
        self.volatility_threshold = 0.02  # 2% de variação em 1 minuto

    async def start(self):
        """Inicia o motor Sniper."""
        self.is_running = True
        print("Motor Sniper ZIA iniciado.")
        
        while self.is_running:
            try:
                for symbol in self.symbols:
                    # 1. Monitoramento de Volatilidade em Tempo Real
                    current_price = redis_cache.get_price(symbol)
                    previous_price = redis_cache.get_state(f"prev_price_{symbol}")
                    
                    if previous_price:
                        price_change = abs(current_price - previous_price) / previous_price
                        
                        # 2. Detecção de Evento de Volatilidade
                        if price_change > self.volatility_threshold:
                            print(f"Evento Sniper detectado para {symbol}: Variação de {price_change:.2%}")
                            
                            # 3. Execução Rápida (Exemplo: Scalping)
                            action = "buy" if current_price > previous_price else "sell"
                            order_data = {
                                "symbol": symbol,
                                "action": action,
                                "quantity": 0.1,  # Quantidade fixa para o exemplo
                                "price": current_price,
                                "confidence": 0.95  # Alta confiança em eventos de volatilidade
                            }
                            
                            # 4. Execução de Ordem Sniper
                            execution_result = await execution_engine.execute_order(order_data)
                            
                            if execution_result['status'] == "success":
                                print(f"Ordem Sniper executada com sucesso: {execution_result['order_id']}")
                                
                    # 5. Atualiza o preço anterior no cache Redis
                    redis_cache.set_state(f"prev_price_{symbol}", current_price, expire=60)
                    
                await asyncio.sleep(1)  # Monitoramento a cada 1 segundo
            except Exception as e:
                print(f"Erro no loop do motor Sniper: {e}")
                await asyncio.sleep(5)

    def stop(self):
        """Para o motor Sniper."""
        self.is_running = False
        print("Motor Sniper ZIA parado.")

sniper_engine = SniperEngine()
