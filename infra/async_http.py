from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx

from monitoring.metrics import PROVIDER_REQUESTS

logger = logging.getLogger(__name__)


class ProviderCircuitOpen(RuntimeError):
    """Raised when a provider is temporarily isolated after repeated failures."""


@dataclass
class _ProviderState:
    failures: int = 0
    opened_until: float = 0.0
    last_error: str = ""
    last_success_at: float = 0.0


class AsyncProviderHTTP:
    """Shared async HTTP transport with bounded concurrency and provider isolation.

    Only idempotent GET/HEAD calls are retried. Synchronous read-only providers may
    use ``run_sync``; it offloads work from the event loop and applies the same
    bounded retry/circuit policy. Cancelling a timed-out thread cannot stop the
    third-party operation itself, so the per-provider circuit limits repeat work.

    The cache is deliberately process-local. It prevents duplicate requests inside a
    process, while Redis or an edge cache remains responsible for cross-replica
    coordination in a deployed environment.
    """

    _RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
    _IDEMPOTENT_METHODS = {"GET", "HEAD"}

    def __init__(
        self,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_connections: int = 50,
        max_keepalive_connections: int = 20,
        provider_concurrency: int = 10,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.25,
        backoff_max_seconds: float = 2.0,
        jitter_ratio: float = 0.25,
    ):
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self.max_retries = max(0, min(int(max_retries), 5))
        base = float(backoff_base_seconds)
        ceiling = float(backoff_max_seconds)
        jitter = float(jitter_ratio)
        self.backoff_base_seconds = min(5.0, max(0.0, base if math.isfinite(base) else 0.25))
        self.backoff_max_seconds = max(
            self.backoff_base_seconds,
            min(30.0, max(0.0, ceiling if math.isfinite(ceiling) else 2.0)),
        )
        self.jitter_ratio = max(0.0, min(jitter if math.isfinite(jitter) else 0.25, 1.0))
        self._client_owned = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=max(read_timeout, 1.0),
                connect=max(connect_timeout, 0.1),
                read=max(read_timeout, 1.0),
                write=max(read_timeout, 1.0),
                pool=max(connect_timeout, 0.1),
            ),
            limits=httpx.Limits(
                max_connections=max(1, int(max_connections)),
                max_keepalive_connections=max(1, int(max_keepalive_connections)),
            ),
            follow_redirects=True,
        )
        self._provider_concurrency = max(1, int(provider_concurrency))
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._states: Dict[str, _ProviderState] = {}
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._state_guard = asyncio.Lock()

    def _state(self, provider: str) -> _ProviderState:
        return self._states.setdefault(provider, _ProviderState())

    def _semaphore(self, provider: str) -> asyncio.Semaphore:
        return self._semaphores.setdefault(provider, asyncio.Semaphore(self._provider_concurrency))

    @staticmethod
    def _cache_key(provider: str, url: str, params: Optional[Dict[str, Any]], response_type: str) -> str:
        normalized_params = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
        return repr((provider, url, normalized_params, response_type))

    async def _check_circuit(self, provider: str) -> None:
        async with self._state_guard:
            state = self._state(provider)
            if state.opened_until > time.monotonic():
                remaining = state.opened_until - time.monotonic()
                raise ProviderCircuitOpen(f"provider {provider} isolado por mais {remaining:.1f}s")
            if state.opened_until:
                state.opened_until = 0.0
                state.failures = 0

    async def _success(self, provider: str) -> None:
        async with self._state_guard:
            state = self._state(provider)
            state.failures = 0
            state.opened_until = 0.0
            state.last_error = ""
            state.last_success_at = time.time()

    async def _failure(self, provider: str, exc: Exception) -> None:
        async with self._state_guard:
            state = self._state(provider)
            state.failures += 1
            state.last_error = str(exc)
            if state.failures >= self.failure_threshold:
                state.opened_until = time.monotonic() + self.cooldown_seconds
                logger.warning("Circuit breaker abriu para %s por %.1fs", provider, self.cooldown_seconds)

    def _retryable(self, method: str, exc: Exception) -> bool:
        if method.upper() not in self._IDEMPOTENT_METHODS:
            return False
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in self._RETRYABLE_STATUS_CODES
        return isinstance(exc, (httpx.TransportError, TimeoutError))

    @staticmethod
    def _retryable_sync(exc: Exception) -> bool:
        module = type(exc).__module__
        return isinstance(exc, (OSError, TimeoutError)) or module.startswith(
            ("requests.exceptions", "urllib3.exceptions")
        )

    def _retry_delay(self, attempt: int, exc: Exception | None = None) -> float:
        ceiling = min(self.backoff_max_seconds, self.backoff_base_seconds * (2 ** max(0, attempt)))
        delay = 0.0
        if ceiling > 0:
            delay = random.uniform(ceiling * (1.0 - self.jitter_ratio), ceiling * (1.0 + self.jitter_ratio))
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            retry_after = exc.response.headers.get("Retry-After")
            try:
                delay = max(delay, float(retry_after))
            except (TypeError, ValueError):
                pass
        return min(self.backoff_max_seconds, delay)

    async def _request(
        self,
        provider: str,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        ttl_seconds: float = 0.0,
        response_type: str = "json",
    ) -> Any:
        key = self._cache_key(provider, url, params, response_type)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        if cached:
            self._cache.pop(key, None)

        attempt = 0
        while True:
            await self._check_circuit(provider)
            try:
                async with self._semaphore(provider):
                    response = await self.client.request(method, url, params=params, headers=headers or {})
                    response.raise_for_status()
                    value = response.json() if response_type == "json" else response.text
                await self._success(provider)
                PROVIDER_REQUESTS.labels(provider=provider, status="success").inc()
                if ttl_seconds > 0:
                    self._cache[key] = (time.monotonic() + float(ttl_seconds), value)
                return value
            except Exception as exc:
                PROVIDER_REQUESTS.labels(provider=provider, status="error").inc()
                await self._failure(provider, exc)
                if attempt >= self.max_retries or not self._retryable(method, exc):
                    raise
                delay = self._retry_delay(attempt, exc)
                attempt += 1
                if delay:
                    await asyncio.sleep(delay)

    async def run_sync(
        self,
        provider: str,
        operation: Callable[[], Any],
        timeout_seconds: float,
    ) -> Any:
        """Run a read-only blocking provider operation outside the event loop."""
        timeout = max(0.05, float(timeout_seconds))
        attempt = 0
        while True:
            await self._check_circuit(provider)
            try:
                async with self._semaphore(provider):
                    value = await asyncio.wait_for(asyncio.to_thread(operation), timeout=timeout)
                await self._success(provider)
                PROVIDER_REQUESTS.labels(provider=provider, status="success").inc()
                return value
            except Exception as exc:
                PROVIDER_REQUESTS.labels(provider=provider, status="error").inc()
                await self._failure(provider, exc)
                if attempt >= self.max_retries or not self._retryable_sync(exc):
                    raise
                delay = self._retry_delay(attempt)
                attempt += 1
                if delay:
                    await asyncio.sleep(delay)

    async def get_json(
        self,
        provider: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        ttl_seconds: float = 0.0,
    ) -> Any:
        return await self._request(provider, "GET", url, params, headers, ttl_seconds, "json")

    async def get_text(
        self,
        provider: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        ttl_seconds: float = 0.0,
    ) -> str:
        return await self._request(provider, "GET", url, None, headers, ttl_seconds, "text")

    def health(self, provider: Optional[str] = None) -> Dict[str, Any]:
        providers = [provider] if provider else sorted(self._states)
        now = time.monotonic()
        result: Dict[str, Any] = {}
        for name in providers:
            state = self._states.get(name, _ProviderState())
            result[name] = {
                "ok": state.failures == 0 and state.opened_until <= now,
                "failures": state.failures,
                "circuit_open": state.opened_until > now,
                "cooldown_remaining_seconds": max(0.0, state.opened_until - now),
                "last_error": state.last_error,
                "last_success_at": state.last_success_at,
            }
        return result

    async def aclose(self) -> None:
        if self._client_owned:
            await self.client.aclose()
