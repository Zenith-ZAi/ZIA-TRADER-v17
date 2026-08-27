from __future__ import annotations

from typing import Any, Callable


class FakeAsyncHTTP:
    def __init__(self, handler: Callable[..., Any]):
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    async def get_json(self, provider: str, url: str, params=None, headers=None, ttl_seconds=0.0):
        self.calls.append({"provider": provider, "url": url, "params": params, "headers": headers, "ttl_seconds": ttl_seconds, "type": "json"})
        return self.handler(url, params, headers)

    async def get_text(self, provider: str, url: str, headers=None, ttl_seconds=0.0):
        self.calls.append({"provider": provider, "url": url, "headers": headers, "ttl_seconds": ttl_seconds, "type": "text"})
        return self.handler(url, None, headers)

    def health(self, provider=None):
        names = [provider] if provider else []
        return {
            name: {"ok": True, "failures": 0, "circuit_open": False, "last_error": ""}
            for name in names
        }

    async def aclose(self):
        return None
