"""Bounded server-side repository scope for persisted client identities.

This module is deliberately narrower than authentication and authorization:
callers must supply an already-authenticated :class:`TrustedCaller`, while the
repository verifies the persisted issuer/subject, tenant membership, and
account ownership in one explicit query.  Unverified JWTs, request payloads,
legacy environment auth, and order permissions are intentionally outside this
contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import BrokerAccountV1, PrincipalV1, TenantMembershipV1, TenantV1


_ALLOWED_ROLES: Final[dict[str, int]] = {"viewer": 10, "trader": 20, "admin": 30}
_SCOPE_UNAVAILABLE = "client scope unavailable"


class ScopeResolutionError(PermissionError):
    """Stable fail-closed error that does not disclose another tenant."""


@dataclass(frozen=True, slots=True)
class TrustedCaller:
    """Issuer/subject supplied by an already-authenticated trusted boundary.

    This value is not a JWT parser and does not validate a token.  The caller
    that creates it is responsible for completing authentication first.  As
    with every in-process Python object, this marker is not a defense against
    hostile code that already runs in the same process.
    """

    issuer: str
    subject: str

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or not self.issuer.strip():
            raise ValueError("trusted caller issuer must be non-empty")
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("trusted caller subject must be non-empty")
        if self.issuer != self.issuer.strip() or self.subject != self.subject.strip():
            raise ValueError("trusted caller identity must be canonical without surrounding whitespace")


def trusted_authenticated_caller(*, issuer: str, subject: str) -> TrustedCaller:
    """Construct the small hand-off object after authentication has succeeded.

    Authentication code is intentionally not implemented here.  In particular,
    passing a decoded-but-unverified payload to this helper would violate the
    caller contract; this helper is only the explicit trusted-boundary handoff.
    """

    return TrustedCaller(issuer=issuer, subject=subject)


# Short name for trusted integration code that already owns the auth boundary.
trusted_caller = trusted_authenticated_caller


@dataclass(frozen=True, slots=True)
class ClientScope:
    """Frozen, server-resolved repository scope.

    The scope identifies one tenant, one persisted principal, and one broker
    account plus its venue/environment.  It is context for repository queries,
    not permission to place orders and not proof of ledger facts.
    """

    tenant_id: str
    principal_id: str
    account_id: str
    venue: str
    environment: str
    role: str


# Name used by repository callers that call this object a repository scope.
RepositoryScope = ClientScope


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


def _unavailable() -> ScopeResolutionError:
    # Keep this message constant: callers must not learn whether an identity,
    # tenant, membership, or account belonging to another tenant exists.
    return ScopeResolutionError(_SCOPE_UNAVAILABLE)


def resolve_client_scope(
    session: Session,
    *,
    caller: TrustedCaller,
    tenant_id: str,
    account_id: str,
    required_role: str,
) -> ClientScope:
    """Resolve an explicit active tenant/account scope for a trusted caller.

    The SQL predicate intentionally includes tenant, account, issuer, subject,
    and active states.  There is no default-account lookup and no path that
    derives scope from a request dictionary or an unverified JWT payload.
    Role requirements are hierarchical (admin >= trader >= viewer), but this
    result still does not authorize order execution.
    """

    if not isinstance(caller, TrustedCaller):
        raise _unavailable()

    canonical_tenant_id = _canonical_uuid(tenant_id)
    canonical_account_id = _canonical_uuid(account_id)
    requested_role = required_role.strip().lower() if isinstance(required_role, str) else ""
    required_level = _ALLOWED_ROLES.get(requested_role)
    if canonical_tenant_id is None or canonical_account_id is None or required_level is None:
        raise _unavailable()

    statement = (
        select(
            TenantV1.id.label("tenant_id"),
            PrincipalV1.id.label("principal_id"),
            BrokerAccountV1.id.label("account_id"),
            BrokerAccountV1.venue.label("venue"),
            BrokerAccountV1.environment.label("environment"),
            TenantMembershipV1.role.label("role"),
        )
        .select_from(TenantV1)
        .join(
            TenantMembershipV1,
            TenantMembershipV1.tenant_id == TenantV1.id,
        )
        .join(
            PrincipalV1,
            PrincipalV1.id == TenantMembershipV1.principal_id,
        )
        .join(
            BrokerAccountV1,
            BrokerAccountV1.tenant_id == TenantV1.id,
        )
        .where(
            TenantV1.id == canonical_tenant_id,
            BrokerAccountV1.id == canonical_account_id,
            PrincipalV1.issuer == caller.issuer,
            PrincipalV1.subject == caller.subject,
            TenantV1.status == "active",
            PrincipalV1.status == "active",
            TenantMembershipV1.status == "active",
            BrokerAccountV1.status == "active",
            TenantMembershipV1.role.in_(
                role for role, level in _ALLOWED_ROLES.items() if level >= required_level
            ),
        )
    )

    row = session.execute(statement).mappings().one_or_none()
    if row is None:
        raise _unavailable()

    return ClientScope(
        tenant_id=row["tenant_id"],
        principal_id=row["principal_id"],
        account_id=row["account_id"],
        venue=row["venue"],
        environment=row["environment"],
        role=row["role"],
    )


# Explicit alternate spelling for internal repository code; both names retain
# the same strict signature and semantics.
resolve_scope = resolve_client_scope


__all__ = [
    "ClientScope",
    "RepositoryScope",
    "ScopeResolutionError",
    "TrustedCaller",
    "resolve_client_scope",
    "resolve_scope",
    "trusted_authenticated_caller",
    "trusted_caller",
]
