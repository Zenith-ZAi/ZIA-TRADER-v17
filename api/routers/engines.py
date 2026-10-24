"""Engine lifecycle, runtime reload, and dashboard websocket routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from api.dependencies import (
    authenticate_websocket,
    get_admin_user,
    get_trader_user,
    get_trading_manager,
)
from api.runtime_services import runtime_status_payload, start_engine, stop_engines

router = APIRouter()


@router.post("/runtime/reload")
async def reload_runtime(
    request: Request,
    current_user: dict[str, Any] = Depends(get_admin_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    profile = manager.reload_runtime_config()
    return {
        "reloaded": True,
        "profile": profile,
        "status": runtime_status_payload(request.app),
    }


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket) -> None:
    try:
        authenticate_websocket(websocket)
        if getattr(websocket.app.state, "runtime", None) is None:
            raise HTTPException(status_code=503, detail="application_runtime_not_started")
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(runtime_status_payload(websocket.app))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@router.post("/trading/start")
async def start_trading(
    request: Request,
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    started = await start_engine(request.app, "trading", manager.start_trading)
    return {
        "message": "Motor de Trading iniciado." if started else "Motor de Trading já estava em execução.",
        "started": started,
    }


@router.post("/sniper/start")
async def start_sniper(
    request: Request,
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    started = await start_engine(request.app, "sniper", manager.start_sniper)
    return {
        "message": "Motor Sniper iniciado." if started else "Motor Sniper já estava em execução.",
        "started": started,
    }


@router.post("/trading/stop")
async def stop_trading(
    request: Request,
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, str]:
    await stop_engines(request.app, manager)
    return {"message": "Todos os motores parados."}
