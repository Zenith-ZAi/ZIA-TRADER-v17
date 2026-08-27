from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)


class _InMemoryFallback:
    """Store local de testes/desenvolvimento; não é fonte de verdade para autonomia."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._expiry: dict[str, float] = {}

    def _purge(self, key: str) -> None:
        exp = self._expiry.get(key)
        if exp is not None and time.time() >= exp:
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self._purge(key)
        if nx and key in self._store:
            return False
        self._store[key] = value
        if ex:
            self._expiry[key] = time.time() + int(ex)
        return True

    def expire(self, key: str, seconds: int):
        self._purge(key)
        if key in self._store:
            self._expiry[key] = time.time() + int(seconds)
            return True
        return False

    def get(self, key: str) -> Optional[str]:
        self._purge(key)
        return self._store.get(key)

    def delete(self, key: str):
        self._store.pop(key, None)
        self._expiry.pop(key, None)
        return 1


class RedisLease:
    """Lease renovável para impedir decisões concorrentes por chave."""

    def __init__(self, cache: "RedisCache", key: str, token: str, ttl_seconds: int, renew_seconds: int):
        self.cache = cache
        self.key = key
        self.token = token
        self.ttl_seconds = max(2, int(ttl_seconds))
        self.renew_seconds = max(1, int(renew_seconds))
        self._released = False
        self._renew_task: asyncio.Task | None = None

    def start(self) -> "RedisLease":
        self._renew_task = asyncio.create_task(self._renew_loop())
        return self

    async def _renew_loop(self) -> None:
        try:
            while not self._released:
                await asyncio.sleep(self.renew_seconds)
                if not self._released and not await self.cache.renew_lock(self.key, self.token, self.ttl_seconds):
                    logger.warning("Lock Redis perdido antes do fim do ciclo: %s", self.key)
                    self._released = True
        except asyncio.CancelledError:
            return

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._renew_task is not None:
            self._renew_task.cancel()
            await asyncio.gather(self._renew_task, return_exceptions=True)
        await self.cache.release_lock(self.key, self.token)

    async def __aenter__(self) -> "RedisLease":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()


class RedisCache:
    def __init__(self, redis_url: str):
        self.redis_client = None
        try:
            import redis as redis_lib
            client = redis_lib.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            self.redis_client = client
            logger.info("RedisCache conectado ao Redis persistente")
        except Exception as exc:
            logger.warning("Redis não disponível (%s). Usando fallback em memória.", exc)
            self.redis_client = _InMemoryFallback()

    @property
    def is_persistent(self) -> bool:
        return not isinstance(self.redis_client, _InMemoryFallback)

    def health(self) -> dict[str, object]:
        return {
            "persistent": self.is_persistent,
            "backend": "redis" if self.is_persistent else "memory_fallback",
        }

    async def _call(self, method: str, *args, **kwargs):
        if isinstance(self.redis_client, _InMemoryFallback):
            return getattr(self.redis_client, method)(*args, **kwargs)
        return await asyncio.to_thread(getattr(self.redis_client, method), *args, **kwargs)

    async def set_state(self, key: str, value: Any, expire: Optional[int] = None):
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            await self._call("set", key, value)
            if expire:
                await self._call("expire", key, expire)
        except Exception as exc:
            logger.error("Erro ao definir estado para a chave %s: %s", key, exc)

    async def get_state(self, key: str) -> Optional[Any]:
        try:
            value = await self._call("get", key)
            if value:
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return None
        except Exception as exc:
            logger.error("Erro ao obter estado para a chave %s: %s", key, exc)
            return None

    async def delete_state(self, key: str):
        try:
            await self._call("delete", key)
        except Exception as exc:
            logger.error("Erro ao deletar estado para a chave %s: %s", key, exc)

    async def try_acquire_lock(self, key: str, ttl_seconds: int = 30, token: str | None = None) -> str | None:
        owner = token or uuid.uuid4().hex
        try:
            acquired = await self._call("set", key, owner, nx=True, ex=max(2, int(ttl_seconds)))
            return owner if acquired else None
        except TypeError:
            # Clients fake/antigos sem NX: nunca assumimos exclusão segura.
            logger.error("Backend Redis sem suporte seguro a SET NX; lock recusado: %s", key)
            return None
        except Exception as exc:
            logger.error("Falha ao adquirir lock %s: %s", key, exc)
            return None

    async def acquire_lock(
        self,
        key: str,
        ttl_seconds: int = 30,
        renew_seconds: int = 10,
    ) -> RedisLease | None:
        token = await self.try_acquire_lock(key, ttl_seconds=ttl_seconds)
        if token is None:
            return None
        return RedisLease(self, key, token, ttl_seconds, renew_seconds).start()

    async def renew_lock(self, key: str, token: str, ttl_seconds: int = 30) -> bool:
        try:
            current = await self._call("get", key)
            if current != token:
                return False
            return bool(await self._call("expire", key, max(2, int(ttl_seconds))))
        except Exception as exc:
            logger.warning("Falha ao renovar lock %s: %s", key, exc)
            return False

    async def release_lock(self, key: str, token: str) -> bool:
        try:
            current = await self._call("get", key)
            if current != token:
                return False
            return bool(await self._call("delete", key))
        except Exception as exc:
            logger.warning("Falha ao liberar lock %s: %s", key, exc)
            return False
