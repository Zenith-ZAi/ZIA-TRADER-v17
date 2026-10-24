"""Health, liveness, metrics, and minimal service metadata routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import generate_latest

from api.dependencies import get_current_active_user
from api.runtime_services import health_payload

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    """Readiness/liveness response; secrets and account payloads are omitted."""
    return health_payload(request.app)


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Detailed operational health for the proxy and supervised operation."""
    return health_payload(request.app)


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type="text/plain")


@router.get("/")
async def root_rate_limited(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_active_user),
) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }
