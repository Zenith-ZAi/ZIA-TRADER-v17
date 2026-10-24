"""Authentication and identity-facing API routes."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from api.dependencies import (
    auth_users,
    get_app_settings,
    get_current_active_user,
    get_trader_user,
)
from security.jwt_utils import create_access_token

router = APIRouter()


@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    settings: Any = Depends(get_app_settings),
) -> dict[str, str]:
    users = auth_users(settings)
    if not users:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    user = users.get(form_data.username)
    if not user or not secrets.compare_digest(user["password"], form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        secret_key=settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me")
async def read_users_me(
    current_user: dict[str, Any] = Depends(get_current_active_user),
) -> dict[str, Any]:
    return {
        "username": current_user["username"],
        "roles": list(current_user.get("roles", [])),
    }


@router.get("/test_rate_limit")
async def test_rate_limit(
    current_user: dict[str, Any] = Depends(get_current_active_user),
) -> dict[str, str]:
    return {"status": "ok", "user": current_user["username"]}


@router.get("/users/me/items/")
async def read_own_items(
    current_user: dict[str, Any] = Depends(get_trader_user),
) -> list[dict[str, Any]]:
    return [{"item_id": "Foo", "owner": current_user["username"]}]
