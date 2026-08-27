from __future__ import annotations

import hashlib
import uuid
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from security.rate_limiter import RateLimiter
from monitoring.structured_logging import correlation_id_var


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propaga um ID não sensível para correlacionar request, logs e métricas."""

    async def dispatch(self, request: Request, call_next: Callable):
        correlation_id = request.headers.get("x-correlation-id", "").strip()[:128] or uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            correlation_id_var.reset(token)


class RequestRateLimitMiddleware(BaseHTTPMiddleware):
    """Aplica rate limit antes das rotas, por IP e pelo token/usuário."""

    def __init__(self, app, settings) -> None:
        super().__init__(app)
        self.ip_limiter = RateLimiter(settings.API_RATE_LIMIT_BY_IP, settings.API_RATE_LIMIT_INTERVAL)
        self.user_limiter = RateLimiter(settings.API_RATE_LIMIT_BY_USER, settings.API_RATE_LIMIT_INTERVAL)

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or (request.client.host if request.client else "unknown")

    @staticmethod
    def _user_key(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        if not authorization:
            return "anonymous"
        return "token:" + hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]

    async def dispatch(self, request: Request, call_next: Callable):
        ip_key = self._client_ip(request)
        if not self.ip_limiter.allow(ip_key):
            return JSONResponse(
                status_code=429,
                content={"detail": "rate_limit_exceeded", "scope": "ip"},
                headers={"Retry-After": str(self.ip_limiter.retry_after(ip_key))},
            )
        user_key = self._user_key(request)
        if not self.user_limiter.allow(user_key):
            return JSONResponse(
                status_code=429,
                content={"detail": "rate_limit_exceeded", "scope": "user"},
                headers={"Retry-After": str(self.user_limiter.retry_after(user_key))},
            )
        return await call_next(request)
