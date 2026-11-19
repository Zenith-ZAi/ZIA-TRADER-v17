from __future__ import annotations

import asyncio

import pytest

from infra.redis_cache import RedisLease


class FakeCache:
    def __init__(self):
        self.release_calls = []
        self.release_started = asyncio.Event()
        self.allow_release = asyncio.Event()

    async def renew_lock(self, *_args, **_kwargs):
        return False

    async def release_lock(self, key, token):
        self.release_started.set()
        await self.allow_release.wait()
        self.release_calls.append((key, token))
        return True


def test_release_still_compare_deletes_after_renew_loop_marked_lease_lost():
    async def run():
        cache = FakeCache()
        cache.allow_release.set()
        lease = RedisLease(cache, "lock:key", "owner-token", 30, 30)
        lease._released = True  # mesma condição quando _renew_loop perde o lock

        await lease.release()
        await lease.release()

        assert cache.release_calls == [("lock:key", "owner-token")]

    asyncio.run(run())


def test_release_cleanup_continues_when_owning_task_is_cancelled():
    async def run():
        cache = FakeCache()
        lease = RedisLease(cache, "lock:key", "owner-token", 30, 30)
        lease.start()
        owner = asyncio.create_task(lease.release())
        await cache.release_started.wait()

        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner

        cache.allow_release.set()
        assert lease._release_task is not None
        await lease._release_task
        assert cache.release_calls == [("lock:key", "owner-token")]
        assert lease._renew_task is not None and lease._renew_task.done()

    asyncio.run(run())
