from __future__ import annotations

import asyncio
import os
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from core.client_scope import TrustedCaller
from core.credential_vault import (
    CredentialInput,
    CredentialVault,
    CredentialVaultUnavailableError,
)
from database import (
    Base,
    BrokerAccountV1,
    CredentialVaultAuditV1,
    PrincipalV1,
    TenantMembershipV1,
    TenantV1,
)
from execution.exchange_gateway import (
    ExchangeGateway,
    ExchangeGatewayDeniedError,
    ExchangeGatewayDisabledError,
    ExchangeGatewayUnavailableError,
)


KMS_KEY_ARN = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
KMS_REGION = "us-east-1"
_TABLES = tuple(
    Base.metadata.tables[name]
    for name in (
        "tenant_v1",
        "principal_v1",
        "tenant_membership_v1",
        "broker_account_v1",
        "credential_vault_v1",
        "credential_vault_audit_v1",
    )
)


class FakeKms:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.envelopes: dict[bytes, tuple[bytes, dict[str, str]]] = {}

    def generate_data_key(self, *, key_arn: str, encryption_context: dict[str, str]):
        self.calls.append("generate")
        key = os.urandom(32)
        wrapped = b"gateway-test-key-" + len(self.calls).to_bytes(4, "big")
        self.envelopes[wrapped] = (key, dict(encryption_context))
        return bytearray(key), wrapped

    def decrypt_data_key(
        self,
        *,
        key_arn: str,
        encrypted_data_key: bytes,
        encryption_context: dict[str, str],
    ):
        self.calls.append("decrypt")
        stored = self.envelopes.get(encrypted_data_key)
        if stored is None or stored[1] != encryption_context:
            raise RuntimeError("invalid test KMS envelope")
        return bytearray(stored[0])


class FakeReadOnlyAdapter:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls: list[tuple[str, object]] = []
        self.closed = False
        self.place_order_calls = 0

    async def fetch_balance(self):
        self.calls.append(("fetch_balance", None))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("request failed with api-secret-sensitive-B")
        return {"USDT": {"free": "12.50"}}

    async def fetch_open_orders(self):
        self.calls.append(("fetch_open_orders", None))
        return []

    async def fetch_trades(self, *, symbol: str | None = None):
        self.calls.append(("fetch_trades", symbol))
        return [{"symbol": symbol, "id": "trade-1"}]

    async def close(self):
        self.closed = True


class CancelledCloseAdapter(FakeReadOnlyAdapter):
    async def close(self):
        self.closed = True
        raise asyncio.CancelledError()


@pytest.fixture

def gateway_env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gateway.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        tenant = TenantV1(name=f"tenant-{uuid4()}")
        session.add(tenant)
        session.flush()

        def add_principal(*, role: str, subject: str) -> PrincipalV1:
            principal = PrincipalV1(issuer="https://identity.example", subject=subject)
            session.add(principal)
            session.flush()
            session.add(
                TenantMembershipV1(
                    tenant_id=tenant.id,
                    principal_id=principal.id,
                    role=role,
                    status="active",
                )
            )
            session.flush()
            return principal

        admin = add_principal(role="admin", subject=f"admin-{uuid4()}")
        trader = add_principal(role="trader", subject=f"trader-{uuid4()}")
        viewer = add_principal(role="viewer", subject=f"viewer-{uuid4()}")
        account = BrokerAccountV1(
            tenant_id=tenant.id,
            venue="binance",
            environment="testnet",
            account_ref=f"opaque-{uuid4()}",
            status="active",
        )
        session.add(account)
        session.commit()
        tenant_id, account_id = tenant.id, account.id
        admin_id, trader_id, viewer_id = admin.id, trader.id, viewer.id
        admin_issuer, admin_subject = admin.issuer, admin.subject
        trader_issuer, trader_subject = trader.issuer, trader.subject
        viewer_issuer, viewer_subject = viewer.issuer, viewer.subject

    kms = FakeKms()
    settings = SimpleNamespace(
        CREDENTIAL_VAULT_ENABLED=True,
        CREDENTIAL_VAULT_KMS_PROVIDER="aws",
        CREDENTIAL_VAULT_AWS_REGION=KMS_REGION,
        CREDENTIAL_VAULT_KMS_KEY_ARN=KMS_KEY_ARN,
    )
    vault = CredentialVault(settings, data_key_provider=kms)
    admin_caller = TrustedCaller(issuer=admin_issuer, subject=admin_subject)
    with factory() as session:
        vault.store(
            session,
            caller=admin_caller,
            tenant_id=tenant_id,
            account_id=account_id,
            credentials=CredentialInput(
                api_key="api-key-sensitive-A",
                api_secret="api-secret-sensitive-B",
                passphrase="passphrase-sensitive-C",
            ),
        )
        session.commit()

    yield SimpleNamespace(
        engine=engine,
        factory=factory,
        vault=vault,
        kms=kms,
        tenant_id=tenant_id,
        account_id=account_id,
        admin_id=admin_id,
        trader_id=trader_id,
        viewer_id=viewer_id,
        admin_caller=admin_caller,
        trader_caller=TrustedCaller(issuer=trader_issuer, subject=trader_subject),
        viewer_caller=TrustedCaller(issuer=viewer_issuer, subject=viewer_subject),
    )
    engine.dispose()


def _gateway(env, *, enabled=True, fail=False, delay=0.0, timeout_seconds=15.0):
    env.adapters = []
    env.leases = []

    def build_adapter(scope, material):
        # Only the short-lived adapter factory gets the secret lease.
        assert scope.tenant_id == env.tenant_id
        assert scope.account_id == env.account_id
        assert scope.environment == "testnet"
        with env.factory() as audit_session:
            assert audit_session.scalars(
                select(CredentialVaultAuditV1).where(
                    CredentialVaultAuditV1.event_type == "accessed"
                )
            ).all()
        assert material.api_key == "api-key-sensitive-A"
        assert material.api_secret == "api-secret-sensitive-B"
        assert material.passphrase == "passphrase-sensitive-C"
        env.leases.append(material)
        adapter = FakeReadOnlyAdapter(fail=fail, delay=delay)
        env.adapters.append(adapter)
        return adapter

    return ExchangeGateway(
        session_factory=env.factory,
        vault=env.vault,
        adapter_factories={("binance", "testnet"): build_adapter},
        enabled=enabled,
        timeout_seconds=timeout_seconds,
    )


def test_exchange_gateway_is_disabled_by_default_and_does_not_retrieve_secrets(gateway_env):
    env = gateway_env
    gateway = _gateway(env, enabled=False)

    with pytest.raises(ExchangeGatewayDisabledError, match="^exchange gateway is disabled$"):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )

    assert env.kms.calls == ["generate"]
    assert env.adapters == []


def test_balance_read_uses_account_scope_and_commits_vault_audit_before_network(gateway_env):
    env = gateway_env
    gateway = _gateway(env)

    result = asyncio.run(
        gateway.fetch_balance(
            caller=env.trader_caller,
            tenant_id=env.tenant_id,
            account_id=env.account_id,
        )
    )

    assert result == {"USDT": {"free": "12.50"}}
    assert env.adapters[0].calls == [("fetch_balance", None)]
    assert env.adapters[0].closed is True
    assert env.kms.calls == ["generate", "decrypt"]
    assert env.adapters[0].place_order_calls == 0
    with pytest.raises(CredentialVaultUnavailableError, match="^credential lease is closed$"):
        _ = env.leases[0].api_key
    with env.factory() as session:
        audit = session.scalars(
            select(CredentialVaultAuditV1).where(
                CredentialVaultAuditV1.event_type == "accessed"
            )
        ).all()
    assert len(audit) == 1
    assert audit[0].broker_account_id == env.account_id


def test_viewer_cannot_access_private_exchange_credentials_or_adapter(gateway_env):
    env = gateway_env
    gateway = _gateway(env)

    with pytest.raises(ExchangeGatewayDeniedError, match="^exchange request denied$"):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.viewer_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )

    assert env.kms.calls == ["generate"]
    assert env.adapters == []


def test_open_orders_is_an_explicit_read_operation(gateway_env):
    env = gateway_env
    gateway = _gateway(env)

    assert asyncio.run(
        gateway.fetch_open_orders(
            caller=env.trader_caller,
            tenant_id=env.tenant_id,
            account_id=env.account_id,
        )
    ) == []
    assert env.adapters[0].calls == [("fetch_open_orders", None)]
    assert env.adapters[0].place_order_calls == 0


def test_membership_revocation_is_rechecked_before_each_exchange_call(gateway_env):
    env = gateway_env
    gateway = _gateway(env)
    asyncio.run(
        gateway.fetch_balance(
            caller=env.trader_caller,
            tenant_id=env.tenant_id,
            account_id=env.account_id,
        )
    )

    with env.factory() as session:
        membership = session.scalar(
            select(TenantMembershipV1).where(
                TenantMembershipV1.principal_id == env.trader_id
            )
        )
        membership.status = "inactive"
        session.commit()

    with pytest.raises(ExchangeGatewayDeniedError, match="^exchange request denied$"):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )
    assert env.kms.calls == ["generate", "decrypt"]
    assert len(env.adapters) == 1


def test_gateway_never_routes_live_accounts(gateway_env):
    env = gateway_env
    with env.factory() as session:
        account = session.get(BrokerAccountV1, env.account_id)
        account.environment = "live"
        session.commit()
    gateway = _gateway(env)

    with pytest.raises(ExchangeGatewayDeniedError, match="^exchange request denied$"):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )

    assert env.kms.calls == ["generate"]
    assert env.adapters == []


def test_invalid_trade_symbol_is_rejected_before_scope_or_vault_access(gateway_env):
    env = gateway_env
    gateway = _gateway(env)

    with pytest.raises(ExchangeGatewayDeniedError, match="^exchange request denied$"):
        asyncio.run(
            gateway.fetch_trades(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
                symbol="BTC/USDT\nAuthorization: secret",
            )
        )

    assert env.kms.calls == ["generate"]
    assert env.adapters == []


def test_trade_reads_are_explicit_and_exchange_errors_are_redacted(gateway_env):
    env = gateway_env
    gateway = _gateway(env)

    result = asyncio.run(
        gateway.fetch_trades(
            caller=env.trader_caller,
            tenant_id=env.tenant_id,
            account_id=env.account_id,
            symbol="BTC/USDT",
        )
    )
    assert result == [{"symbol": "BTC/USDT", "id": "trade-1"}]
    assert env.adapters[0].calls == [("fetch_trades", "BTC/USDT")]

    failing_gateway = _gateway(env, fail=True)
    with pytest.raises(ExchangeGatewayUnavailableError) as caught:
        asyncio.run(
            failing_gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )
    assert "api-secret-sensitive-B" not in str(caught.value)
    assert "api-secret-sensitive-B" not in repr(caught.value)
    assert not hasattr(failing_gateway, "place_order")


def test_credential_lease_is_closed_even_if_adapter_cleanup_is_cancelled(gateway_env):
    env = gateway_env
    adapters = []
    leases = []

    def build_adapter(scope, material):
        assert material.api_key == "api-key-sensitive-A"
        leases.append(material)
        adapter = CancelledCloseAdapter()
        adapters.append(adapter)
        return adapter

    gateway = ExchangeGateway(
        session_factory=env.factory,
        vault=env.vault,
        adapter_factories={("binance", "testnet"): build_adapter},
        enabled=True,
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )

    assert adapters[0].closed is True
    with pytest.raises(CredentialVaultUnavailableError, match="^credential lease is closed$"):
        _ = leases[0].api_key


def test_cancellation_during_scope_and_kms_resolution_closes_abandoned_lease(gateway_env):
    env = gateway_env
    gateway = _gateway(env)
    worker_started = threading.Event()
    release_worker = threading.Event()
    leases = []
    original_resolver = gateway._resolve_scope_and_retrieve

    def delayed_resolver(**kwargs):
        worker_started.set()
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test worker release timed out")
        result = original_resolver(**kwargs)
        leases.append(result[1])
        return result

    gateway._resolve_scope_and_retrieve = delayed_resolver

    async def exercise_cancellation():
        operation = asyncio.create_task(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )
        for _ in range(200):
            if worker_started.is_set():
                break
            await asyncio.sleep(0.005)
        assert worker_started.is_set()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        release_worker.set()
        for _ in range(200):
            if leases:
                try:
                    _ = leases[0].api_key
                except CredentialVaultUnavailableError as exc:
                    assert str(exc) == "credential lease is closed"
                    return
            await asyncio.sleep(0.005)
        pytest.fail("cancelled resolution returned a lease that was not wiped")

    try:
        asyncio.run(exercise_cancellation())
    finally:
        release_worker.set()

    assert env.adapters == []


def test_exchange_timeout_closes_adapter_and_credential_lease(gateway_env):
    env = gateway_env
    gateway = _gateway(env, delay=1.0, timeout_seconds=0.01)

    with pytest.raises(ExchangeGatewayUnavailableError):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )

    assert env.adapters[0].closed is True
    with pytest.raises(CredentialVaultUnavailableError, match="^credential lease is closed$"):
        _ = env.leases[0].api_key


def test_exchange_adapter_with_no_allowlist_entry_is_not_constructed(gateway_env):
    env = gateway_env
    gateway = ExchangeGateway(
        session_factory=env.factory,
        vault=env.vault,
        adapter_factories={},
        enabled=True,
    )

    with pytest.raises(ExchangeGatewayUnavailableError):
        asyncio.run(
            gateway.fetch_balance(
                caller=env.trader_caller,
                tenant_id=env.tenant_id,
                account_id=env.account_id,
            )
        )

    assert env.kms.calls == ["generate"]
