"""Authentication and identity-facing API routes."""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from api.dependencies import auth_users, get_app_settings, get_current_active_user, get_trader_user
from api.routers.passkeys import router as passkeys_router
from security.jwt_utils import create_access_token
from security.passkey_service import PREAUTH_TTL_SECONDS, credential_for_user, normalized_username, webauthn_config

router = APIRouter()
router.include_router(passkeys_router)


def _runtime_database(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    manager = getattr(runtime, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="passkey_storage_unavailable")
    return manager


@router.post("/token")
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    settings: Any = Depends(get_app_settings),
) -> dict[str, Any]:
    users = auth_users(settings)
    if not users:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication is not configured.")
    user = next(
        (candidate for configured_name, candidate in users.items()
         if normalized_username(configured_name) == normalized_username(form_data.username)),
        None,
    )
    if not user or not secrets.compare_digest(user["password"], form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if settings.PASSKEY_MFA_REQUIRED:
        # No password-only access JWT is created in this branch.
        webauthn_config(settings)
        credential = credential_for_user(_runtime_database(request), user["username"])
        scope = "passkey:authenticate" if credential else "passkey:register"
        return {
            "mfa_required": True,
            "preauth_token": create_access_token(
                data={
                    "sub": user["username"],
                    "token_use": "passkey_preauth",
                    "scope": scope,
                    "mfa_verified": False,
                },
                expires_delta=timedelta(seconds=PREAUTH_TTL_SECONDS),
                secret_key=settings.SECRET_KEY,
                algorithm=settings.ALGORITHM,
            ),
            "next": "passkey_authentication" if credential else "passkey_registration",
            "token_type": "bearer",
        }
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        secret_key=settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me")
async def read_users_me(current_user: dict[str, Any] = Depends(get_current_active_user)) -> dict[str, Any]:
    return {"username": current_user["username"], "roles": list(current_user.get("roles", []))}


@router.get("/test_rate_limit")
async def test_rate_limit(current_user: dict[str, Any] = Depends(get_current_active_user)) -> dict[str, str]:
    return {"status": "ok", "user": current_user["username"]}


@router.get("/users/me/items/")
async def read_own_items(current_user: dict[str, Any] = Depends(get_trader_user)) -> list[dict[str, Any]]:
    return [{"item_id": "Foo", "owner": current_user["username"]}]
