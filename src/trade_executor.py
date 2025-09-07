import asyncio
import time
from typing import Dict, Optional

from enhanced_broker_api import EnhancedBrokerAPI, OrderResult
from config import config
from utils import setup_logging

logger = setup_logging(__name__)

class AdvancedOrderExecutor:
    """
    Executor de ordens avançado com gestão de posição e ordens OCO (One Cancels Other).
    """
    
    def __init__(self, broker: EnhancedBrokerAPI):
        self.broker = broker
        self.active_orders = {}  # Dicionário para rastrear ordens ativas (principal, stop-loss, take-profit)
        self.current_positions = {} # {symbol: {size: float, entry_price: float}}
        
    async def execute_trade(self, signal: str, confidence: float, symbol: str = 'BTC/USDT',
                            position_size_usd: float = 100.0) -> Dict:
        """
        Executa uma negociação baseada no sinal recebido, com gestão de risco integrada.
        
        Args:
            signal: Sinal de negociação ('buy', 'sell', 'hold')
            confidence: Nível de confiança (0-100)
            symbol: Par de negociação
            position_size_usd: Tamanho da posição em USD (para novas entradas)
            
        Returns:
            Resultado da execução
        """
        logger.info(f"🎯 Executando trade: {signal.upper()} com confiança {confidence:.2f}% para {symbol}")
        
        if signal == 'hold':
            return {'status': 'no_action', 'message': 'Sinal de manter posição'}
        
        current_price = self.broker.get_current_price(symbol) # Síncrono para simplicidade, pode ser assíncrono
        if current_price == 0.0: # Fallback para preço dummy
            logger.error(f"Não foi possível obter preço atual para {symbol}. Abortando trade.")
            return {'status': 'failed', 'message': 'Preço atual indisponível'}

        # Gerenciar posições existentes
        if symbol in self.current_positions:
            current_position = self.current_positions[symbol]
            
            # Fechar posição existente se o sinal for oposto
            if (signal == 'buy' and current_position['size'] < 0) or \
               (signal == 'sell' and current_position['size'] > 0):
                logger.info(f"Sinal oposto detectado. Fechando posição existente de {current_position['size']:.4f} {symbol}")
                close_result = await self._close_position(symbol, current_position['size'], current_price)
                if close_result['status'] != 'success':
                    return close_result # Falha ao fechar posição
                # Após fechar, a posição é considerada zerada para o próximo passo
                self.current_positions.pop(symbol, None)
                self.active_orders.pop(symbol, None) # Limpar ordens ativas para este símbolo

            # Se o sinal for na mesma direção, mas já há uma posição, não abrir nova
            elif (signal == 'buy' and current_position['size'] > 0) or \
                 (signal == 'sell' and current_position['size'] < 0):
                logger.info(f"Já existe uma posição {signal} aberta para {symbol}. Não abrindo nova.")
                return {'status': 'no_action', 'message': 'Posição já aberta na mesma direção'}

        # Abrir nova posição
        quantity = position_size_usd / current_price
        
        # Colocar ordem principal
        order_result = await self.broker.place_order_async(symbol, 'market', signal, quantity)
        
        if not order_result.success:
            logger.error(f"Falha ao colocar ordem principal: {order_result.error_message}")
            return {'status': 'failed', 'message': order_result.error_message}
        
        logger.info(f"✅ Ordem principal executada: {order_result.order_id}")
        
        # Atualizar posição
        self._update_position(symbol, signal, quantity, order_result.price)
        
        # Colocar ordens de stop-loss e take-profit (OCO)
        await self._place_oco_orders(symbol, order_result.price, confidence)
        
        return {
            'status': 'success',
            'order': order_result.__dict__,
            'position_size': self.current_positions[symbol]['size'],
            'entry_price': self.current_positions[symbol]['entry_price']
        }
    
    async def _close_position(self, symbol: str, size: float, current_price: float) -> Dict:
        """
        Fecha uma posição existente.
        """
        side = 'sell' if size > 0 else 'buy'
        quantity = abs(size)
        
        # Cancelar ordens OCO existentes para este símbolo
        await self.cancel_oco_orders(symbol)
        
        close_order_result = await self.broker.place_order_async(symbol, 'market', side, quantity)
        
        if not close_order_result.success:
            logger.error(f"Falha ao fechar posição: {close_order_result.error_message}")
            return {'status': 'failed', 'message': close_order_result.error_message}
        
        logger.info(f"✅ Posição de {symbol} fechada. Ordem: {close_order_result.order_id}")
        self.current_positions.pop(symbol, None)
        return {'status': 'success', 'message': 'Posição fechada com sucesso'}

    def _update_position(self, symbol: str, side: str, quantity: float, price: float):
        """
        Atualiza o registro da posição atual.
        """
        if symbol not in self.current_positions:
            self.current_positions[symbol] = {'size': 0.0, 'entry_price': 0.0}
            
        current_size = self.current_positions[symbol]['size']
        current_entry_price = self.current_positions[symbol]['entry_price']
        
        if side == 'buy':
            new_size = current_size + quantity
            new_entry_price = ((current_size * current_entry_price) + (quantity * price)) / new_size
        else: # sell
            new_size = current_size - quantity
            new_entry_price = ((current_size * current_entry_price) - (quantity * price)) / new_size
        
        self.current_positions[symbol]['size'] = new_size
        self.current_positions[symbol]['entry_price'] = new_entry_price
        
        if abs(new_size) < 1e-8: # Posição efetivamente zerada
            self.current_positions.pop(symbol, None)
            logger.info(f"Posição para {symbol} zerada.")

    async def _place_oco_orders(self, symbol: str, entry_price: float, confidence: float):
        """
        Coloca ordens OCO (One Cancels Other) para stop-loss e take-profit.
        """
        if symbol not in self.current_positions or abs(self.current_positions[symbol]['size']) < 1e-8:
            logger.warning(f"Não há posição aberta para {symbol} para colocar ordens OCO.")
            return
            
        position_size = self.current_positions[symbol]['size']
        side = 'sell' if position_size > 0 else 'buy' # Lado oposto à posição
        quantity = abs(position_size)
        
        # Calcular níveis de stop-loss e take-profit baseados na confiança e configurações
        confidence_factor = confidence / 100.0
        stop_loss_pct = config.trading.base_stop_loss * (2 - confidence_factor)  # Menos confiança = stop mais largo
        take_profit_pct = config.trading.base_take_profit * (1 + confidence_factor) # Mais confiança = TP mais distante
        
        if position_size > 0:  # Posição de compra (long)
            stop_price = entry_price * (1 - stop_loss_pct)
            tp_price = entry_price * (1 + take_profit_pct)
        else:  # Posição de venda (short)
            stop_price = entry_price * (1 + stop_loss_pct)
            tp_price = entry_price * (1 - take_profit_pct)
        
        # Colocar ordens limit para SL/TP
        # Nota: CCXT não tem OCO nativo para todas as exchanges. Simular com duas ordens limit.
        # Em um ambiente real, usaríamos a funcionalidade OCO da exchange se disponível.
        
        stop_order_result = await self.broker.place_order_async(symbol, 'limit', side, quantity, stop_price)
        tp_order_result = await self.broker.place_order_async(symbol, 'limit', side, quantity, tp_price)
        
        if stop_order_result.success:
            self.active_orders.setdefault(symbol, {})['stop_loss'] = stop_order_result.__dict__
            logger.info(f"🛡️ Stop-loss para {symbol} colocado em ${stop_price:.2f}")
        else:
            logger.error(f"Falha ao colocar stop-loss para {symbol}: {stop_order_result.error_message}")
            
        if tp_order_result.success:
            self.active_orders.setdefault(symbol, {})['take_profit'] = tp_order_result.__dict__
            logger.info(f"🎯 Take-profit para {symbol} colocado em ${tp_price:.2f}")
        else:
            logger.error(f"Falha ao colocar take-profit para {symbol}: {tp_order_result.error_message}")

    async def cancel_oco_orders(self, symbol: str):
        """
        Cancela ordens OCO (stop-loss e take-profit) para um símbolo específico.
        """
        if symbol in self.active_orders:
            for order_type, order_info in self.active_orders[symbol].items():
                if 'order_id' in order_info:
                    logger.info(f"Cancelando ordem {order_type} {order_info['order_id']} para {symbol}")
                    await self.broker.cancel_order_async(order_info['order_id'], symbol)
            self.active_orders.pop(symbol, None)
            logger.info(f"Ordens OCO para {symbol} canceladas.")

    def get_position_status(self, symbol: Optional[str] = None) -> Dict:
        """
        Retorna o status da posição atual para um símbolo ou todos.
        """
        if symbol:
            return self.current_positions.get(symbol, {'size': 0.0, 'entry_price': 0.0})
        return self.current_positions

    def get_active_orders(self, symbol: Optional[str] = None) -> Dict:
        """
        Retorna as ordens ativas para um símbolo ou todas.
        """
        if symbol:
            return self.active_orders.get(symbol, {})
        return self.active_orders

if __name__ == "__main__":
    async def test_executor():
        logger.info("🚀 Testando executor de ordens avançado...")
        
        # Inicializar broker (em modo sandbox)
        broker = EnhancedBrokerAPI('binance')
        executor = AdvancedOrderExecutor(broker)
        
        symbol = 'BTC/USDT'
        position_size_usd = 100.0
        
        # Simular execução de compra
        logger.info(f"\n--- Teste de Compra ({symbol}) ---")
        result_buy = await executor.execute_trade('buy', 98.5, symbol, position_size_usd)
        logger.info(f"Resultado da compra: {result_buy}")
        logger.info(f"Status da posição: {executor.get_position_status(symbol)}")
        logger.info(f"Ordens ativas: {executor.get_active_orders(symbol)}")
        
        # Simular tempo passando
        await asyncio.sleep(2) 
        
        # Simular execução de venda (fechando posição de compra)
        logger.info(f"\n--- Teste de Venda (Fechamento de Compra) ({symbol}) ---")
        result_sell = await executor.execute_trade('sell', 97.2, symbol, position_size_usd) # position_size_usd é ignorado ao fechar
        logger.info(f"Resultado da venda: {result_sell}")
        logger.info(f"Status da posição: {executor.get_position_status(symbol)}")
        logger.info(f"Ordens ativas: {executor.get_active_orders(symbol)}")
        
        # Simular tempo passando
        await asyncio.sleep(2)
        
        # Simular nova compra
        logger.info(f"\n--- Teste de Nova Compra ({symbol}) ---")
        result_buy_2 = await executor.execute_trade('buy', 99.0, symbol, position_size_usd)
        logger.info(f"Resultado da segunda compra: {result_buy_2}")
        logger.info(f"Status da posição: {executor.get_position_status(symbol)}")
        logger.info(f"Ordens ativas: {executor.get_active_orders(symbol)}")
        
        # Cleanup
        await executor.cancel_oco_orders(symbol)
        broker.cleanup()
        logger.info("Teste concluído!")

    asyncio.run(test_executor())


