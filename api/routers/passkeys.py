"""WebAuthn JSON endpoints integrated with env-backed auth_users and JWT sessions."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.dependencies import auth_users, get_passkey_registration_user
from security.jwt_utils import create_access_token
from security.passkey_service import (
    PREAUTH_TTL_SECONDS,
    authentication_options,
    credential_for_user,
    normalized_username,
    registration_options,
    verify_authentication,
    verify_registration,
    webauthn_config,
)

router = APIRouter(prefix="/passkey", tags=["passkey"])


class UsernameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def username_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("username cannot be blank")
        return value


class CredentialRequest(UsernameRequest):
    credential: dict[str, Any]

    @field_validator("credential")
    @classmethod
    def credential_size_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), ensure_ascii=True)) > 65536:
            raise ValueError("credential payload too large")
        return value


class RegistrationCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential: dict[str, Any]

    @field_validator("credential")
    @classmethod
    def credential_size_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), ensure_ascii=True)) > 65536:
            raise ValueError("credential payload too large")
        return value


def _configured_identity(settings: Any, username: str) -> dict[str, Any]:
    canonical = normalized_username(username)
    for configured_name, user in auth_users(settings).items():
        if normalized_username(configured_name) == canonical:
            return user
    raise HTTPException(status_code=401, detail="passkey_authentication_unavailable")


def _database_manager(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    manager = getattr(runtime, "db_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="passkey_storage_unavailable")
    return manager


@router.post("/registration/options")
def begin_registration(
    request: Request,
    current_user: dict[str, Any] = Depends(get_passkey_registration_user),
) -> dict[str, Any]:
    settings = request.app.state.settings
    if not settings.PASSKEY_ENROLLMENT_ENABLED:
        raise HTTPException(status_code=403, detail="passkey_enrollment_disabled")
    manager = _database_manager(request)
    return registration_options(manager, settings, current_user["username"])


@router.post("/registration/verify")
def finish_registration(
    body: RegistrationCredentialRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_passkey_registration_user),
) -> dict[str, bool]:
    settings = request.app.state.settings
    if not settings.PASSKEY_ENROLLMENT_ENABLED:
        raise HTTPException(status_code=403, detail="passkey_enrollment_disabled")
    manager = _database_manager(request)
    verify_registration(manager, settings, current_user["username"], body.credential)
    return {"registered": True}


@router.post("/authentication/options")
def begin_authentication(
    body: UsernameRequest,
    request: Request,
) -> dict[str, Any]:
    settings = request.app.state.settings
    user = _configured_identity(settings, body.username)
    manager = _database_manager(request)
    return authentication_options(manager, settings, user["username"])


@router.post("/authentication/verify")
def finish_authentication(
    body: CredentialRequest,
    request: Request,
) -> dict[str, str]:
    settings = request.app.state.settings
    user = _configured_identity(settings, body.username)
    manager = _database_manager(request)
    verify_authentication(manager, settings, user["username"], body.credential)
    access_token = create_access_token(
        data={"sub": user["username"], "mfa_verified": True},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        secret_key=settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return {"access_token": access_token, "token_type": "bearer"}
