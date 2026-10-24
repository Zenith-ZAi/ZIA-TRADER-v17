"""Authenticated operations and supervised order endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from api.dependencies import (
    get_admin_user,
    get_database_manager,
    get_trader_user,
    get_trading_manager,
)
from api.runtime_services import runtime_status_payload

router = APIRouter()


@router.get("/admin/dashboard")
async def admin_dashboard(
    request: Request,
    current_user: dict[str, Any] = Depends(get_admin_user),
) -> dict[str, Any]:
    return {
        "message": f"Welcome, admin {current_user['username']}",
        "status": runtime_status_payload(request.app),
    }


@router.post("/admin/kill-switch")
async def admin_kill_switch(
    reason: str = Body(..., embed=True, min_length=3, max_length=200),
    current_user: dict[str, Any] = Depends(get_admin_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    return await manager.trigger_kill_switch(reason, actor=current_user["username"])


@router.get("/status")
async def status_alias(
    request: Request,
    current_user: dict[str, Any] = Depends(get_trader_user),
    db_manager: Any = Depends(get_database_manager),
) -> dict[str, Any]:
    account = db_manager.get_account_state("default_account")
    positions = db_manager.get_open_positions("default_account")
    daily = db_manager.get_daily_pnl(
        "default_account",
        datetime.now(timezone.utc).replace(tzinfo=None),
    )
    payload = runtime_status_payload(request.app)
    payload.update(
        {
            "balance": float(account.balance) if account else 0.0,
            "initial_capital": float(account.initial_capital) if account else 0.0,
            "daily_pnl": float(daily.pnl) if daily else 0.0,
            "open_positions": [
                {
                    "symbol": item.symbol,
                    "quantity": float(item.quantity),
                    "entry_price": float(item.entry_price),
                    "current_price": float(item.current_price),
                    "unrealized_pnl": float(item.unrealized_pnl or 0.0),
                }
                for item in positions
            ],
        }
    )
    return payload


@router.post("/order")
async def create_order(
    order: dict[str, Any] = Body(...),
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    payload = dict(order)
    requested_source = str(payload.pop("source", "manual")).lower()
    # AI-originated orders are internal and cannot use this public endpoint.
    if requested_source != "manual":
        raise HTTPException(status_code=400, detail="source só pode ser manual nesta rota")
    payload.pop("confirmed", None)
    try:
        return await manager.order_manager.submit(
            payload,
            source="manual",
            confirmed=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/order/confirm")
async def confirm_order(
    request: dict[str, Any] = Body(...),
    current_user: dict[str, Any] = Depends(get_trader_user),
    manager: Any = Depends(get_trading_manager),
) -> dict[str, Any]:
    token = str(request.get("confirmation_token", ""))
    approved = bool(request.get("approved", True))
    try:
        return await manager.order_manager.confirm(token, approved=approved)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/logs")
async def logs_alias(
    current_user: dict[str, Any] = Depends(get_trader_user),
    db_manager: Any = Depends(get_database_manager),
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    logs = [
        item
        for item in db_manager.get_system_logs("default_account")
        if item.timestamp and item.timestamp >= cutoff
    ]
    return {
        "since": cutoff.isoformat(),
        "logs": [
            {
                "timestamp": item.timestamp.isoformat(),
                "level": item.level,
                "module": item.module,
                "message": item.message,
            }
            for item in logs
        ],
    }


@router.get("/dashboard/status")
async def dashboard_status(
    request: Request,
    current_user: dict[str, Any] = Depends(get_trader_user),
) -> dict[str, Any]:
    return runtime_status_payload(request.app)
