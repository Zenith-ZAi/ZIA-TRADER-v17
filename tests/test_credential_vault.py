from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import boto3
import pytest
from botocore.stub import Stubber
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from core.client_scope import ScopeResolutionError, TrustedCaller
from core.credential_vault import (
    AwsKmsDataKeyProvider,
    CredentialInput,
    CredentialVault,
    CredentialVaultConflictError,
    CredentialVaultDisabledError,
    CredentialVaultIntegrityError,
    CredentialVaultUnavailableError,
)
from database import (
    Base,
    BrokerAccountV1,
    CredentialVaultAuditV1,
    CredentialVaultV1,
    PrincipalV1,
    TenantMembershipV1,
    TenantV1,
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
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.envelopes: dict[bytes, tuple[bytes, dict[str, str]]] = {}
        self.counter = 0
        self.fail_generate = False

    def generate_data_key(self, *, key_arn: str, encryption_context: dict[str, str]):
        self.calls.append(("generate", key_arn, dict(encryption_context)))
        if self.fail_generate:
            raise CredentialVaultUnavailableError("credential vault cryptographic operation failed")
        self.counter += 1
        data_key = os.urandom(32)
        wrapped = b"wrapped-test-key-" + self.counter.to_bytes(4, "big")
        self.envelopes[wrapped] = (data_key, dict(encryption_context))
        return bytearray(data_key), wrapped

    def decrypt_data_key(
        self,
        *,
        key_arn: str,
        encrypted_data_key: bytes,
        encryption_context: dict[str, str],
    ):
        self.calls.append(("decrypt", key_arn, dict(encryption_context)))
        entry = self.envelopes.get(encrypted_data_key)
        if entry is None or entry[1] != encryption_context:
            raise CredentialVaultUnavailableError("credential vault cryptographic operation failed")
        return bytearray(entry[0])


def _settings(*, enabled: bool = True):
    return SimpleNamespace(
        CREDENTIAL_VAULT_ENABLED=enabled,
        CREDENTIAL_VAULT_KMS_PROVIDER="aws",
        CREDENTIAL_VAULT_AWS_REGION=KMS_REGION,
        CREDENTIAL_VAULT_KMS_KEY_ARN=KMS_KEY_ARN,
    )


def _new_principal(session, tenant: TenantV1, *, role: str, subject: str) -> PrincipalV1:
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


def _caller(principal: PrincipalV1) -> TrustedCaller:
    return TrustedCaller(issuer=principal.issuer, subject=principal.subject)


@pytest.fixture
def vault_env():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    tenant = TenantV1(name=f"tenant-{uuid4()}")
    session.add(tenant)
    session.flush()
    admin = _new_principal(session, tenant, role="admin", subject=f"admin-{uuid4()}")
    trader = _new_principal(session, tenant, role="trader", subject=f"trader-{uuid4()}")
    viewer = _new_principal(session, tenant, role="viewer", subject=f"viewer-{uuid4()}")
    account = BrokerAccountV1(
        tenant_id=tenant.id,
        venue="binance",
        environment="testnet",
        account_ref=f"opaque-{uuid4()}",
        status="active",
    )
    session.add(account)
    session.commit()
    kms = FakeKms()
    vault = CredentialVault(_settings(), data_key_provider=kms)
    try:
        yield SimpleNamespace(
            session=session,
            engine=engine,
            tenant=tenant,
            admin=admin,
            trader=trader,
            viewer=viewer,
            account=account,
            kms=kms,
            vault=vault,
        )
    finally:
        session.close()
        engine.dispose()


def _credential_input(api_key: str = "api-key-sensitive-A", api_secret: str = "api-secret-sensitive-B"):
    return CredentialInput(api_key=api_key, api_secret=api_secret, passphrase="passphrase-sensitive-C")


def _store(env, credentials=None, *, expected_version=None):
    return env.vault.store(
        env.session,
        caller=_caller(env.admin),
        tenant_id=env.tenant.id,
        account_id=env.account.id,
        credentials=credentials or _credential_input(),
        expected_version=expected_version,
    )


def test_store_encrypts_credentials_and_retrieval_returns_redacted_short_lease(vault_env):
    env = vault_env
    source = _credential_input()
    info = _store(env, source)
    env.session.commit()

    row = env.session.scalar(select(CredentialVaultV1))
    assert info.version == 1
    assert info.status == "active"
    assert row is not None and row.status == "active"
    assert source.api_key.encode() not in row.ciphertext
    assert source.api_secret.encode() not in row.ciphertext
    assert source.passphrase.encode() not in row.ciphertext
    assert not {"api_key", "api_secret", "passphrase"}.intersection(
        column.name for column in CredentialVaultV1.__table__.columns
    )
    assert "api-key-sensitive-A" not in repr(row)
    assert "api-secret-sensitive-B" not in repr(source)
    assert "passphrase-sensitive-C" not in repr(source)

    material = env.vault.retrieve(
        env.session,
        caller=_caller(env.trader),
        tenant_id=env.tenant.id,
        account_id=env.account.id,
    )
    assert "api-key-sensitive-A" not in repr(material)
    with material as lease:
        assert lease.api_key == source.api_key
        assert lease.api_secret == source.api_secret
        assert lease.passphrase == source.passphrase
    with pytest.raises(CredentialVaultUnavailableError, match="^credential lease is closed$"):
        _ = material.api_secret

    events = list(env.session.scalars(select(CredentialVaultAuditV1).order_by(CredentialVaultAuditV1.event_type)))
    assert [event.event_type for event in events] == ["accessed", "created"]
    assert {event.actor_principal_id for event in events} == {env.admin.id, env.trader.id}
    assert all("api-secret-sensitive-B" not in repr(event) for event in events)


def test_role_and_explicit_tenant_account_scope_are_checked_before_kms(vault_env):
    env = vault_env
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        env.vault.store(
            env.session,
            caller=_caller(env.viewer),
            tenant_id=env.tenant.id,
            account_id=env.account.id,
            credentials=_credential_input(),
        )
    assert env.kms.calls == []

    _store(env)
    env.session.commit()
    calls_before = len(env.kms.calls)
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        env.vault.retrieve(
            env.session,
            caller=_caller(env.viewer),
            tenant_id=env.tenant.id,
            account_id=env.account.id,
        )
    assert len(env.kms.calls) == calls_before

    other_tenant = TenantV1(name=f"other-{uuid4()}")
    env.session.add(other_tenant)
    env.session.flush()
    other_admin = _new_principal(env.session, other_tenant, role="admin", subject=f"other-{uuid4()}")
    other_account = BrokerAccountV1(
        tenant_id=other_tenant.id,
        venue="binance",
        environment="testnet",
        account_ref=f"opaque-{uuid4()}",
    )
    env.session.add(other_account)
    env.session.commit()
    calls_before = len(env.kms.calls)
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        env.vault.retrieve(
            env.session,
            caller=_caller(other_admin),
            tenant_id=other_tenant.id,
            account_id=env.account.id,
        )
    assert len(env.kms.calls) == calls_before


def test_tampered_ciphertext_fails_authentication_without_secret_disclosure(vault_env):
    env = vault_env
    _store(env)
    env.session.commit()
    row = env.session.scalar(select(CredentialVaultV1))
    original = row.ciphertext
    row.ciphertext = original[:-1] + bytes([original[-1] ^ 1])
    env.session.commit()

    with pytest.raises(CredentialVaultIntegrityError, match="^credential envelope is invalid$") as error:
        env.vault.retrieve(
            env.session,
            caller=_caller(env.trader),
            tenant_id=env.tenant.id,
            account_id=env.account.id,
        )
    assert "api-secret-sensitive-B" not in str(error.value)


def test_rotation_uses_compare_and_swap_version_and_new_data_key(vault_env):
    env = vault_env
    assert _store(env).version == 1
    env.session.commit()

    rotated = _store(
        env,
        _credential_input("api-key-v2", "api-secret-v2"),
        expected_version=1,
    )
    env.session.commit()
    assert rotated == type(rotated)(version=2, status="active")
    assert sum(call[0] == "generate" for call in env.kms.calls) == 2

    with pytest.raises(CredentialVaultConflictError, match="^credential version conflict$"):
        _store(env, _credential_input("stale-key", "stale-secret"), expected_version=1)
    env.session.rollback()

    with env.vault.retrieve(
        env.session,
        caller=_caller(env.trader),
        tenant_id=env.tenant.id,
        account_id=env.account.id,
    ) as material:
        assert material.api_key == "api-key-v2"
        assert material.api_secret == "api-secret-v2"

    row = env.session.scalar(select(CredentialVaultV1))
    assert row.version == 2
    assert [item.event_type for item in env.session.scalars(select(CredentialVaultAuditV1))].count("rotated") == 1


def test_revocation_erases_current_envelope_and_reactivation_requires_version(vault_env):
    env = vault_env
    _store(env)
    env.session.commit()
    revoked = env.vault.revoke(
        env.session,
        caller=_caller(env.admin),
        tenant_id=env.tenant.id,
        account_id=env.account.id,
        expected_version=1,
    )
    env.session.commit()
    assert revoked.version == 2
    assert revoked.status == "revoked"
    row = env.session.scalar(select(CredentialVaultV1))
    assert row.status == "revoked"
    assert row.encrypted_data_key is None and row.nonce is None and row.ciphertext is None
    calls_before = len(env.kms.calls)
    with pytest.raises(CredentialVaultUnavailableError, match="^credential unavailable$"):
        env.vault.retrieve(
            env.session,
            caller=_caller(env.trader),
            tenant_id=env.tenant.id,
            account_id=env.account.id,
        )
    assert len(env.kms.calls) == calls_before

    reactivated = _store(env, _credential_input("new-key", "new-secret"), expected_version=2)
    assert reactivated.version == 3
    assert reactivated.status == "active"


def test_kms_failure_does_not_persist_plaintext_or_partial_record(vault_env):
    env = vault_env
    env.kms.fail_generate = True
    with pytest.raises(CredentialVaultUnavailableError, match="^credential vault cryptographic operation failed$") as error:
        _store(env)
    assert "api-secret-sensitive-B" not in str(error.value)
    assert env.session.scalar(select(CredentialVaultV1)) is None
    assert env.session.scalar(select(CredentialVaultAuditV1)) is None


def test_vault_and_audit_ids_require_canonical_lowercase_uuid_shape(vault_env):
    from datetime import datetime, timezone

    from sqlalchemy.exc import IntegrityError

    env = vault_env
    now = datetime.now(timezone.utc)
    noncanonical_id = "abcdef0g-1234-1234-1234-123456789012"

    with pytest.raises(IntegrityError):
        env.session.execute(
            CredentialVaultV1.__table__.insert().values(
                id=noncanonical_id,
                broker_account_id=env.account.id,
                version=1,
                status="active",
                kms_key_arn=KMS_KEY_ARN,
                encrypted_data_key=b"wrapped-data-key",
                nonce=b"N" * 12,
                ciphertext=b"C" * 16,
                updated_by_principal_id=env.admin.id,
                created_at=now,
                updated_at=now,
            )
        )
    env.session.rollback()

    with pytest.raises(IntegrityError):
        env.session.execute(
            CredentialVaultAuditV1.__table__.insert().values(
                id=noncanonical_id,
                broker_account_id=env.account.id,
                actor_principal_id=env.admin.id,
                event_type="created",
                credential_version=1,
                occurred_at=now,
            )
        )
    env.session.rollback()


def test_aws_kms_adapter_rejects_key_arn_outside_configured_region():
    with pytest.raises(CredentialVaultDisabledError, match="^AWS KMS configuration is invalid$"):
        AwsKmsDataKeyProvider(
            region="us-west-2",
            key_arn=KMS_KEY_ARN,
            client=object(),
        )


def test_disabled_vault_refuses_secret_operations_even_with_injected_provider(vault_env):
    env = vault_env
    disabled = CredentialVault(_settings(enabled=False), data_key_provider=env.kms)
    with pytest.raises(CredentialVaultDisabledError, match="^credential vault is disabled or unavailable$"):
        disabled.store(
            env.session,
            caller=_caller(env.admin),
            tenant_id=env.tenant.id,
            account_id=env.account.id,
            credentials=_credential_input(),
        )
    assert env.kms.calls == []


def test_boto3_adapter_uses_aes256_exact_context_and_explicit_key_arn():
    client = boto3.client(
        "kms",
        region_name=KMS_REGION,
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
    )
    provider = AwsKmsDataKeyProvider(region=KMS_REGION, key_arn=KMS_KEY_ARN, client=client)
    context = {
        "application": "zia-trader",
        "purpose": "exchange-credential-v1",
        "tenant_id": "tenant-public-id",
        "account_id": "account-public-id",
        "credential_id": "credential-public-id",
        "version": "1",
    }
    plaintext_key = b"K" * 32
    wrapped_key = b"encrypted-data-key-blob"
    with Stubber(client) as stubber:
        stubber.add_response(
            "generate_data_key",
            {"CiphertextBlob": wrapped_key, "Plaintext": plaintext_key, "KeyId": KMS_KEY_ARN},
            {"KeyId": KMS_KEY_ARN, "KeySpec": "AES_256", "EncryptionContext": context},
        )
        generated, encrypted = provider.generate_data_key(
            key_arn=KMS_KEY_ARN,
            encryption_context=context,
        )
        assert generated == plaintext_key
        assert encrypted == wrapped_key
        generated[:] = b"\x00" * len(generated)

        stubber.add_response(
            "decrypt",
            {"KeyId": KMS_KEY_ARN, "Plaintext": plaintext_key},
            {"CiphertextBlob": wrapped_key, "KeyId": KMS_KEY_ARN, "EncryptionContext": context},
        )
        decrypted = provider.decrypt_data_key(
            key_arn=KMS_KEY_ARN,
            encrypted_data_key=wrapped_key,
            encryption_context=context,
        )
        assert decrypted == plaintext_key
        decrypted[:] = b"\x00" * len(decrypted)
