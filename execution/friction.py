"""Fricção realista e determinística para backtest e Sandbox."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class FrictionResult:
    executed_price: float
    commission: float
    latency_ms: float
    slippage_price: float
    spread_price: float


class ExecutionFriction:
    """Aplica custos de execução sem introduzir aleatoriedade não reproduzível."""

    def __init__(
        self,
        enabled: bool = False,
        min_latency_ms: float = 150.0,
        max_latency_ms: float = 500.0,
        min_slippage_ticks: float = 0.5,
        max_slippage_ticks: float = 2.0,
        commission_rate: float = 0.0005,
        seed: int = 42,
        sleep_enabled: bool = False,
    ) -> None:
        if min_latency_ms < 0 or max_latency_ms < min_latency_ms:
            raise ValueError("intervalo de latência inválido")
        if min_slippage_ticks < 0 or max_slippage_ticks < min_slippage_ticks:
            raise ValueError("intervalo de slippage inválido")
        if commission_rate < 0:
            raise ValueError("comissão não pode ser negativa")
        self.enabled = enabled
        self.min_latency_ms = min_latency_ms
        self.max_latency_ms = max_latency_ms
        self.min_slippage_ticks = min_slippage_ticks
        self.max_slippage_ticks = max_slippage_ticks
        self.commission_rate = commission_rate
        self.sleep_enabled = sleep_enabled
        self._rng = random.Random(seed)

    async def wait_latency(self) -> float:
        if not self.enabled:
            return 0.0
        latency_ms = self._rng.uniform(self.min_latency_ms, self.max_latency_ms)
        if self.sleep_enabled:
            await asyncio.sleep(latency_ms / 1000.0)
        return latency_ms

    def apply(
        self,
        action: str,
        theoretical_price: float,
        quantity: float,
        spread_price: float = 0.0,
        tick_size: float = 0.0,
        latency_ms: float = 0.0,
    ) -> FrictionResult:
        if theoretical_price <= 0 or quantity <= 0:
            raise ValueError("preço e quantidade devem ser positivos")
        if action not in {"buy", "sell"}:
            raise ValueError("ação deve ser buy ou sell")
        if spread_price < 0 or tick_size < 0:
            raise ValueError("spread e tick_size não podem ser negativos")
        if not self.enabled:
            executed_price = theoretical_price
            return FrictionResult(executed_price, 0.0, latency_ms, 0.0, 0.0)
        slippage_ticks = self._rng.uniform(self.min_slippage_ticks, self.max_slippage_ticks)
        slippage_price = slippage_ticks * tick_size
        total_cost = spread_price + slippage_price
        executed_price = theoretical_price + total_cost if action == "buy" else theoretical_price - total_cost
        if executed_price <= 0:
            raise ValueError("fricção gerou preço executado inválido")
        commission = executed_price * quantity * self.commission_rate
        return FrictionResult(executed_price, commission, latency_ms, slippage_price, spread_price)
