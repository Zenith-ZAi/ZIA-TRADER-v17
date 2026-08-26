from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Dict


class RateLimiter:
    """Limitador local por janela fixa, sem bloquear o event loop no middleware."""

    def __init__(self, rate_limit: int, interval: int):
        self.rate_limit = max(1, int(rate_limit))
        self.interval = max(1, int(interval))
        self.clients: Dict[str, list[float]] = defaultdict(list)

    def _prune(self, client_id: str, now: float) -> list[float]:
        recent = [timestamp for timestamp in self.clients[client_id] if timestamp > now - self.interval]
        self.clients[client_id] = recent
        return recent

    def allow(self, client_id: str) -> bool:
        now = time.monotonic()
        recent = self._prune(str(client_id), now)
        if len(recent) >= self.rate_limit:
            return False
        recent.append(now)
        return True

    def retry_after(self, client_id: str) -> int:
        now = time.monotonic()
        recent = self._prune(str(client_id), now)
        if not recent:
            return 0
        return max(1, int(recent[0] + self.interval - now))

    async def __call__(self, client_id: str) -> bool:
        """Compatibilidade com os endpoints existentes: aguarda a janela quando necessário."""
        while not self.allow(client_id):
            await asyncio.sleep(min(1.0, max(0.05, self.retry_after(client_id))))
        return True
