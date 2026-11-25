"""Fail-closed, vault-backed, read-only exchange gateway foundation.

This module is an internal service boundary, not an HTTP router. It resolves
account membership on every request, requires the persisted trader role, reads
credentials from the tenant-scoped vault, commits the access-audit event before
network I/O, and exposes only a narrow read-only adapter contract. Mainnet and
all order-mutating operations are intentionally outside this gate.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from sqlalchemy.orm import Session

from core.client_scope import ClientScope, ScopeResolutionError, TrustedCaller, resolve_client_scope
from core.credential_vault import (
    CredentialMaterial,
    CredentialVault,
    CredentialVaultError,
)


class ExchangeGatewayError(RuntimeError):
    """Base class for safe gateway failures that contain no secret material."""


class ExchangeGatewayDisabledError(ExchangeGatewayError):
    """The explicitly opt-in read-only gateway is disabled."""


class ExchangeGatewayDeniedError(ExchangeGatewayError, PermissionError):
    """The caller, account, role, or requested environment is not allowed."""


class ExchangeGatewayUnavailableError(ExchangeGatewayError):
    """The vault or allowlisted read-only exchange adapter is unavailable."""


class ReadOnlyExchangeAdapter(Protocol):
    """Minimal private-account adapter contract; no order mutation methods exist."""

    async def fetch_balance(self) -> Any: ...

    async def fetch_open_orders(self) -> Any: ...

    async def fetch_trades(self, *, symbol: str | None = None) -> Any: ...

    async def close(self) -> None: ...


ReadOnlyAdapterFactory = Callable[
    [ClientScope, CredentialMaterial], ReadOnlyExchangeAdapter
]

# A deliberately small first environment. A future gate must separately approve
# Demo, paper, and Mainnet routing; they are not aliases for Testnet.
_SUPPORTED_ENVIRONMENTS = frozenset({"testnet"})
_SUPPORTED_READS = frozenset({"fetch_balance", "fetch_open_orders", "fetch_trades"})
_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$")


class ExchangeGateway:
    """Tenant/account-scoped gateway for explicitly allowlisted read operations.

    ``session_factory`` must create a new SQLAlchemy Session per invocation.
    Database and KMS work runs in a worker thread, and the session is closed
    before any exchange network call. The API is intentionally not wired into
    FastAPI until JWT-to-TrustedCaller binding and the endpoint contract are
    independently accepted.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        vault: CredentialVault,
        adapter_factories: Mapping[tuple[str, str], ReadOnlyAdapterFactory],
        enabled: bool = False,
        timeout_seconds: float = 15.0,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("invalid exchange gateway timeout")
        self._session_factory = session_factory
        self._vault = vault
        self._enabled = enabled is True
        self._timeout_seconds = float(timeout_seconds)
        normalized: dict[tuple[str, str], ReadOnlyAdapterFactory] = {}
        for key, factory in adapter_factories.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or not all(isinstance(part, str) and part for part in key)
                or not callable(factory)
            ):
                raise ValueError("invalid exchange gateway adapter registry")
            venue, environment = key
            normalized[(venue.lower(), environment.lower())] = factory
        self._adapter_factories = normalized

    async def fetch_balance(
        self, *, caller: TrustedCaller, tenant_id: str, account_id: str
    ) -> Any:
        return await self._read(
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            operation="fetch_balance",
        )

    async def fetch_open_orders(
        self, *, caller: TrustedCaller, tenant_id: str, account_id: str
    ) -> Any:
        return await self._read(
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            operation="fetch_open_orders",
        )

    async def fetch_trades(
        self,
        *,
        caller: TrustedCaller,
        tenant_id: str,
        account_id: str,
        symbol: str | None = None,
    ) -> Any:
        if symbol is not None and (
            not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None
        ):
            raise ExchangeGatewayDeniedError("exchange request denied")
        return await self._read(
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            operation="fetch_trades",
            symbol=symbol,
        )

    async def _read(
        self,
        *,
        caller: TrustedCaller,
        tenant_id: str,
        account_id: str,
        operation: str,
        symbol: str | None = None,
    ) -> Any:
        if not self._enabled:
            raise ExchangeGatewayDisabledError("exchange gateway is disabled")
        if operation not in _SUPPORTED_READS or not isinstance(caller, TrustedCaller):
            raise ExchangeGatewayDeniedError("exchange request denied")

        scope: ClientScope | None = None
        material: CredentialMaterial | None = None
        adapter: ReadOnlyExchangeAdapter | None = None
        try:
            scope, material = await asyncio.to_thread(
                self._resolve_scope_and_retrieve,
                caller=caller,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            factory = self._adapter_factories.get(
                (scope.venue.lower(), scope.environment.lower())
            )
            if factory is None:
                # This should not be reachable after allowlist validation, but
                # retain a uniform, non-enumerating error if registry changes.
                raise ExchangeGatewayUnavailableError("exchange gateway unavailable")
            adapter = factory(scope, material)
            if inspect.isawaitable(adapter):
                if inspect.iscoroutine(adapter):
                    adapter.close()
                raise ExchangeGatewayUnavailableError("exchange gateway unavailable")
            self._validate_adapter(adapter)
            method = getattr(adapter, operation)
            if operation == "fetch_trades":
                result = await asyncio.wait_for(
                    method(symbol=symbol), timeout=self._timeout_seconds
                )
            else:
                result = await asyncio.wait_for(
                    method(), timeout=self._timeout_seconds
                )
            return result
        except (ExchangeGatewayError,):
            raise
        except ScopeResolutionError:
            raise ExchangeGatewayDeniedError("exchange request denied") from None
        except CredentialVaultError:
            raise ExchangeGatewayUnavailableError("exchange gateway unavailable") from None
        except Exception:
            # Do not forward provider exceptions: adapters sometimes embed
            # request URLs, headers, or credential-bearing request data.
            raise ExchangeGatewayUnavailableError("exchange gateway unavailable") from None
        finally:
            try:
                if adapter is not None:
                    await asyncio.wait_for(adapter.close(), timeout=5.0)
            except Exception:
                # Cleanup diagnostics are intentionally not propagated.
                pass
            finally:
                if material is not None:
                    material.close()

    def _resolve_scope_and_retrieve(
        self, *, caller: TrustedCaller, tenant_id: str, account_id: str
    ) -> tuple[ClientScope, CredentialMaterial]:
        material: CredentialMaterial | None = None
        try:
            with self._session_factory() as session:
                scope = resolve_client_scope(
                    session,
                    caller=caller,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    required_role="trader",
                )
                if scope.environment.lower() not in _SUPPORTED_ENVIRONMENTS:
                    raise ExchangeGatewayDeniedError("exchange request denied")
                if (scope.venue.lower(), scope.environment.lower()) not in self._adapter_factories:
                    raise ExchangeGatewayUnavailableError("exchange gateway unavailable")
                material = self._vault.retrieve(
                    session,
                    caller=caller,
                    tenant_id=tenant_id,
                    account_id=account_id,
                )
                # The vault's accessed event must be durable before external
                # I/O. This session is dedicated to the gateway operation.
                session.commit()
                return scope, material
        except (ExchangeGatewayError, ScopeResolutionError, CredentialVaultError):
            if material is not None:
                material.close()
            raise
        except Exception:
            if material is not None:
                material.close()
            raise ExchangeGatewayUnavailableError("exchange gateway unavailable") from None

    @staticmethod
    def _validate_adapter(adapter: object) -> None:
        if any(not callable(getattr(adapter, name, None)) for name in _SUPPORTED_READS):
            raise ExchangeGatewayUnavailableError("exchange gateway unavailable")
        if not callable(getattr(adapter, "close", None)):
            raise ExchangeGatewayUnavailableError("exchange gateway unavailable")


__all__ = [
    "ExchangeGateway",
    "ExchangeGatewayDeniedError",
    "ExchangeGatewayDisabledError",
    "ExchangeGatewayError",
    "ExchangeGatewayUnavailableError",
    "ReadOnlyExchangeAdapter",
]
