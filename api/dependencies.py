"""Request-scoped dependencies for settings, runtime, and authorization."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import OAuth2PasswordBearer

from security.jwt_utils import verify_token
from security.rbac_utils import is_admin, is_trader


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def get_app_settings(request: Request) -> Any:
    return request.app.state.settings


def get_runtime(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="application_runtime_not_started")
    return runtime


def get_database_manager(request: Request) -> Any:
    return get_runtime(request).db_manager


def get_trading_manager(request: Request) -> Any:
    return get_runtime(request).trading_manager


def auth_users(settings: Any) -> dict[str, dict[str, Any]]:
    """Return explicitly configured users; demo users never exist in production."""
    auth_mode = str(settings.AUTH_MODE).strip().lower()
    environment = str(settings.ENVIRONMENT).strip().lower()
    if auth_mode == "env":
        if not settings.AUTH_USERNAME or not settings.AUTH_PASSWORD:
            return {}
        return {
            settings.AUTH_USERNAME: {
                "username": settings.AUTH_USERNAME,
                "password": settings.AUTH_PASSWORD,
                "roles": ["admin", "trader"],
            }
        }
    if settings.DEMO_AUTH_ENABLED and environment not in {"production", "prod", "staging"}:
        return {
            "user": {
                "username": "user",
                "password": settings.DEMO_USER_PASSWORD,
                "roles": ["trader"],
            },
            "admin": {
                "username": "admin",
                "password": settings.DEMO_ADMIN_PASSWORD,
                "roles": ["admin", "trader"],
            },
        }
    return {}


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
) -> dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    settings = request.app.state.settings
    users = auth_users(settings)
    if not users:
        raise credentials_exception
    payload = verify_token(
        token,
        credentials_exception,
        secret_key=settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise credentials_exception
    user = users.get(username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return current_user


async def get_admin_user(
    current_user: dict[str, Any] = Depends(get_current_active_user),
) -> dict[str, Any]:
    if not is_admin(current_user.get("roles", [])):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


async def get_trader_user(
    current_user: dict[str, Any] = Depends(get_current_active_user),
) -> dict[str, Any]:
    if not is_trader(current_user.get("roles", [])):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


def authenticate_websocket(websocket: WebSocket) -> dict[str, Any]:
    token = websocket.query_params.get("token")
    settings = websocket.app.state.settings
    unauthorized = HTTPException(status_code=401, detail="Token inválido")
    if not token:
        raise HTTPException(status_code=401, detail="Token obrigatório")
    payload = verify_token(
        token,
        unauthorized,
        secret_key=settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise unauthorized
    user = auth_users(settings).get(username)
    if not user or not is_trader(user.get("roles", [])):
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    return user
