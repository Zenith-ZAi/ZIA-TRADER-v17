"""Tenant-scoped exchange credential vault backed by AWS KMS envelope encryption.

Plaintext credential material is never persisted. Every stored version gets a
fresh AES-256 data key from KMS and a fresh 96-bit AES-GCM nonce. The KMS
EncryptionContext and local AES-GCM AAD bind the envelope to its tenant,
account, credential record, and version. Python memory erasure is best-effort;
callers must keep leases short and close them with a context manager.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.client_scope import ClientScope, TrustedCaller, resolve_client_scope
from core.vault_config import valid_aws_kms_key_arn, valid_aws_region
from database import CredentialVaultAuditV1, CredentialVaultV1


_SCHEMA = "zia-exchange-credential-v1"
_PURPOSE = "exchange-credential-v1"
_NONCE_SIZE = 12
_DATA_KEY_SIZE = 32
_MAX_SECRET_BYTES = 8192


class CredentialVaultError(RuntimeError):
    """Base class for safe, non-secret-bearing vault failures."""


class CredentialVaultDisabledError(CredentialVaultError):
    """The vault is disabled or not configured; all secret operations fail closed."""


class CredentialVaultUnavailableError(CredentialVaultError):
    """A generic operational failure that deliberately omits provider details."""


class CredentialVaultIntegrityError(CredentialVaultError):
    """The encrypted envelope could not be authenticated or decoded."""


class CredentialVaultConflictError(CredentialVaultError):
    """A version precondition failed during creation, rotation, or revocation."""


class CredentialVaultInputError(CredentialVaultError, ValueError):
    """Credential input did not satisfy the narrow storage contract."""


class DataKeyProvider(Protocol):
    """Minimal KMS contract; implementations never receive credential plaintext."""

    def generate_data_key(
        self, *, key_arn: str, encryption_context: dict[str, str]
    ) -> tuple[bytearray, bytes]: ...

    def decrypt_data_key(
        self,
        *,
        key_arn: str,
        encrypted_data_key: bytes,
        encryption_context: dict[str, str],
    ) -> bytearray: ...


class AwsKmsDataKeyProvider:
    """AWS KMS adapter using Boto3's default credentials chain, outside app settings."""

    def __init__(self, *, region: str, key_arn: str, client=None) -> None:
        if not valid_aws_region(region) or not valid_aws_kms_key_arn(key_arn, region=region):
            raise CredentialVaultDisabledError("AWS KMS configuration is invalid")
        self._region = region
        self._key_arn = key_arn
        if client is None:
            import boto3

            client = boto3.client("kms", region_name=region)
        self._client = client

    def generate_data_key(
        self, *, key_arn: str, encryption_context: dict[str, str]
    ) -> tuple[bytearray, bytes]:
        if key_arn != self._key_arn:
            raise CredentialVaultUnavailableError("credential vault cryptographic operation failed")
        try:
            response = self._client.generate_data_key(
                KeyId=key_arn,
                KeySpec="AES_256",
                EncryptionContext=dict(encryption_context),
            )
            plaintext = response.get("Plaintext")
            wrapped = response.get("CiphertextBlob")
            if not isinstance(plaintext, (bytes, bytearray)) or len(plaintext) != _DATA_KEY_SIZE:
                raise ValueError("invalid KMS data-key response")
            if not isinstance(wrapped, (bytes, bytearray)) or not wrapped:
                raise ValueError("invalid KMS envelope response")
            return bytearray(plaintext), bytes(wrapped)
        except Exception:
            raise CredentialVaultUnavailableError(
                "credential vault cryptographic operation failed"
            ) from None

    def decrypt_data_key(
        self,
        *,
        key_arn: str,
        encrypted_data_key: bytes,
        encryption_context: dict[str, str],
    ) -> bytearray:
        if key_arn != self._key_arn:
            raise CredentialVaultUnavailableError("credential vault cryptographic operation failed")
        try:
            response = self._client.decrypt(
                CiphertextBlob=encrypted_data_key,
                KeyId=key_arn,
                EncryptionContext=dict(encryption_context),
            )
            plaintext = response.get("Plaintext")
            if not isinstance(plaintext, (bytes, bytearray)) or len(plaintext) != _DATA_KEY_SIZE:
                raise ValueError("invalid KMS data-key response")
            return bytearray(plaintext)
        except Exception:
            raise CredentialVaultUnavailableError(
                "credential vault cryptographic operation failed"
            ) from None


@dataclass(frozen=True, slots=True, repr=False)
class CredentialInput:
    """Short-lived input value; repr intentionally redacts all credential fields."""

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    passphrase: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value in (self.api_key, self.api_secret, self.passphrase):
            if value is None:
                continue
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value.encode("utf-8")) > _MAX_SECRET_BYTES
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise CredentialVaultInputError("invalid credential material")
        if self.api_key is None or self.api_secret is None:
            raise CredentialVaultInputError("invalid credential material")

    def __repr__(self) -> str:
        return "CredentialInput(<redacted>)"


@dataclass(frozen=True, slots=True)
class CredentialVersionInfo:
    version: int
    status: str


@dataclass(slots=True, repr=False)
class CredentialMaterial:
    """Mutable, redacted secret lease returned only after an authorized decrypt."""

    _api_key: bytearray = field(repr=False)
    _api_secret: bytearray = field(repr=False)
    _passphrase: bytearray | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __repr__(self) -> str:
        return "CredentialMaterial(<redacted>)"

    def __enter__(self) -> "CredentialMaterial":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise CredentialVaultUnavailableError("credential lease is closed")

    @property
    def api_key(self) -> str:
        self._ensure_open()
        return self._api_key.decode("utf-8")

    @property
    def api_secret(self) -> str:
        self._ensure_open()
        return self._api_secret.decode("utf-8")

    @property
    def passphrase(self) -> str | None:
        self._ensure_open()
        return self._passphrase.decode("utf-8") if self._passphrase is not None else None

    def close(self) -> None:
        if self._closed:
            return
        _wipe(self._api_key)
        _wipe(self._api_secret)
        if self._passphrase is not None:
            _wipe(self._passphrase)
        self._closed = True


def _wipe(value: bytearray | None) -> None:
    if value is not None:
        value[:] = b"\x00" * len(value)


def _serialize_credentials(credentials: CredentialInput) -> bytearray:
    document = {
        "api_key": credentials.api_key,
        "api_secret": credentials.api_secret,
        "passphrase": credentials.passphrase,
    }
    return bytearray(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _encryption_context(scope: ClientScope, credential_id: str, version: int) -> dict[str, str]:
    # KMS records encryption context in audit output; identifiers are public metadata only.
    return {
        "application": "zia-trader",
        "purpose": _PURPOSE,
        "tenant_id": scope.tenant_id,
        "account_id": scope.account_id,
        "credential_id": credential_id,
        "version": str(version),
    }


def _associated_data(
    scope: ClientScope,
    credential_id: str,
    version: int,
    kms_key_arn: str,
) -> bytes:
    return json.dumps(
        {
            "schema": _SCHEMA,
            "tenant_id": scope.tenant_id,
            "account_id": scope.account_id,
            "credential_id": credential_id,
            "version": version,
            "venue": scope.venue,
            "environment": scope.environment,
            "kms_key_arn": kms_key_arn,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _material_from_plaintext(plaintext: bytearray) -> CredentialMaterial:
    try:
        document = json.loads(plaintext)
        if (
            not isinstance(document, dict)
            or set(document) != {"api_key", "api_secret", "passphrase"}
            or not isinstance(document["api_key"], str)
            or not isinstance(document["api_secret"], str)
            or (document["passphrase"] is not None and not isinstance(document["passphrase"], str))
            or not document["api_key"]
            or not document["api_secret"]
        ):
            raise ValueError("invalid credential document")
        return CredentialMaterial(
            _api_key=bytearray(document["api_key"].encode("utf-8")),
            _api_secret=bytearray(document["api_secret"].encode("utf-8")),
            _passphrase=(
                bytearray(document["passphrase"].encode("utf-8"))
                if document["passphrase"] is not None
                else None
            ),
        )
    except Exception:
        raise CredentialVaultIntegrityError("credential envelope is invalid") from None


class CredentialVault:
    """Tenant- and role-checked vault service; callers supply a live DB session."""

    def __init__(self, settings, *, data_key_provider: DataKeyProvider | None = None) -> None:
        self._enabled = bool(getattr(settings, "CREDENTIAL_VAULT_ENABLED", False))
        self._key_arn = str(getattr(settings, "CREDENTIAL_VAULT_KMS_KEY_ARN", "") or "")
        region = str(getattr(settings, "CREDENTIAL_VAULT_AWS_REGION", "") or "")
        provider_name = str(getattr(settings, "CREDENTIAL_VAULT_KMS_PROVIDER", "aws") or "").lower()
        self._data_key_provider = None
        if self._enabled:
            if (
                provider_name != "aws"
                or not valid_aws_region(region)
                or not valid_aws_kms_key_arn(self._key_arn, region=region)
            ):
                raise CredentialVaultDisabledError("credential vault configuration is invalid")
            self._data_key_provider = data_key_provider or AwsKmsDataKeyProvider(
                region=region,
                key_arn=self._key_arn,
            )

    @staticmethod
    def _resolve_scope(
        session: Session,
        *,
        caller: TrustedCaller,
        tenant_id: str,
        account_id: str,
        required_role: str,
    ) -> ClientScope:
        return resolve_client_scope(
            session,
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            required_role=required_role,
        )

    def _provider(self) -> DataKeyProvider:
        if not self._enabled or self._data_key_provider is None:
            raise CredentialVaultDisabledError("credential vault is disabled or unavailable")
        return self._data_key_provider

    def _seal(
        self,
        *,
        scope: ClientScope,
        credential_id: str,
        version: int,
        key_arn: str,
        credentials: CredentialInput,
    ) -> tuple[bytes, bytes, bytes]:
        provider = self._provider()
        context = _encryption_context(scope, credential_id, version)
        aad = _associated_data(scope, credential_id, version, key_arn)
        plaintext = _serialize_credentials(credentials)
        data_key: bytearray | None = None
        try:
            data_key, wrapped_key = provider.generate_data_key(
                key_arn=key_arn,
                encryption_context=context,
            )
            if len(data_key) != _DATA_KEY_SIZE or not wrapped_key:
                raise CredentialVaultUnavailableError("credential vault cryptographic operation failed")
            nonce = os.urandom(_NONCE_SIZE)
            ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, aad)
            return bytes(wrapped_key), nonce, ciphertext
        except CredentialVaultError:
            raise
        except Exception:
            raise CredentialVaultUnavailableError(
                "credential vault cryptographic operation failed"
            ) from None
        finally:
            _wipe(data_key)
            _wipe(plaintext)

    def store(
        self,
        session: Session,
        *,
        caller: TrustedCaller,
        tenant_id: str,
        account_id: str,
        credentials: CredentialInput,
        expected_version: int | None = None,
    ) -> CredentialVersionInfo:
        scope = self._resolve_scope(
            session,
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            required_role="admin",
        )
        self._provider()  # fail before any database mutation or KMS operation
        if not isinstance(credentials, CredentialInput):
            raise CredentialVaultInputError("invalid credential material")

        row = session.scalar(
            select(CredentialVaultV1)
            .where(CredentialVaultV1.broker_account_id == scope.account_id)
            .with_for_update()
        )
        if row is None:
            if expected_version is not None:
                raise CredentialVaultConflictError("credential version conflict")
            credential_id = str(uuid4())
            version = 1
            event_type = "created"
        else:
            if type(expected_version) is not int or expected_version != row.version:
                raise CredentialVaultConflictError("credential version conflict")
            if row.version >= 2_147_483_647:
                raise CredentialVaultConflictError("credential version exhausted")
            credential_id = row.id
            version = row.version + 1
            event_type = "rotated"

        key_arn = self._key_arn
        wrapped_key, nonce, ciphertext = self._seal(
            scope=scope,
            credential_id=credential_id,
            version=version,
            key_arn=key_arn,
            credentials=credentials,
        )
        if row is None:
            row = CredentialVaultV1(
                id=credential_id,
                broker_account_id=scope.account_id,
                version=version,
                status="active",
                kms_key_arn=key_arn,
                encrypted_data_key=wrapped_key,
                nonce=nonce,
                ciphertext=ciphertext,
                updated_by_principal_id=scope.principal_id,
            )
            session.add(row)
        else:
            row.version = version
            row.status = "active"
            row.kms_key_arn = key_arn
            row.encrypted_data_key = wrapped_key
            row.nonce = nonce
            row.ciphertext = ciphertext
            row.updated_by_principal_id = scope.principal_id
        session.add(
            CredentialVaultAuditV1(
                broker_account_id=scope.account_id,
                actor_principal_id=scope.principal_id,
                event_type=event_type,
                credential_version=version,
            )
        )
        session.flush()
        return CredentialVersionInfo(version=version, status="active")

    def retrieve(
        self,
        session: Session,
        *,
        caller: TrustedCaller,
        tenant_id: str,
        account_id: str,
    ) -> CredentialMaterial:
        scope = self._resolve_scope(
            session,
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            required_role="trader",
        )
        provider = self._provider()
        row = session.scalar(
            select(CredentialVaultV1).where(
                CredentialVaultV1.broker_account_id == scope.account_id,
                CredentialVaultV1.status == "active",
            )
        )
        if (
            row is None
            or row.encrypted_data_key is None
            or row.nonce is None
            or row.ciphertext is None
            or not valid_aws_kms_key_arn(row.kms_key_arn)
        ):
            raise CredentialVaultUnavailableError("credential unavailable")

        context = _encryption_context(scope, row.id, row.version)
        aad = _associated_data(scope, row.id, row.version, row.kms_key_arn)
        data_key: bytearray | None = None
        plaintext: bytearray | None = None
        try:
            data_key = provider.decrypt_data_key(
                key_arn=row.kms_key_arn,
                encrypted_data_key=bytes(row.encrypted_data_key),
                encryption_context=context,
            )
            if len(data_key) != _DATA_KEY_SIZE:
                raise CredentialVaultIntegrityError("credential envelope is invalid")
            plaintext = bytearray(AESGCM(data_key).decrypt(row.nonce, row.ciphertext, aad))
            material = _material_from_plaintext(plaintext)
        except CredentialVaultError:
            raise
        except (InvalidTag, ValueError, TypeError):
            raise CredentialVaultIntegrityError("credential envelope is invalid") from None
        except Exception:
            raise CredentialVaultUnavailableError(
                "credential vault cryptographic operation failed"
            ) from None
        finally:
            _wipe(data_key)
            _wipe(plaintext)

        try:
            session.add(
                CredentialVaultAuditV1(
                    broker_account_id=scope.account_id,
                    actor_principal_id=scope.principal_id,
                    event_type="accessed",
                    credential_version=row.version,
                )
            )
            session.flush()
        except Exception:
            material.close()
            raise CredentialVaultUnavailableError("credential audit write failed") from None
        return material

    def revoke(
        self,
        session: Session,
        *,
        caller: TrustedCaller,
        tenant_id: str,
        account_id: str,
        expected_version: int,
    ) -> CredentialVersionInfo:
        scope = self._resolve_scope(
            session,
            caller=caller,
            tenant_id=tenant_id,
            account_id=account_id,
            required_role="admin",
        )
        if type(expected_version) is not int or expected_version < 1:
            raise CredentialVaultConflictError("credential version conflict")
        row = session.scalar(
            select(CredentialVaultV1)
            .where(CredentialVaultV1.broker_account_id == scope.account_id)
            .with_for_update()
        )
        if row is None or row.status != "active" or row.version != expected_version:
            raise CredentialVaultConflictError("credential version conflict")
        if row.version >= 2_147_483_647:
            raise CredentialVaultConflictError("credential version exhausted")

        row.version += 1
        row.status = "revoked"
        row.encrypted_data_key = None
        row.nonce = None
        row.ciphertext = None
        row.updated_by_principal_id = scope.principal_id
        session.add(
            CredentialVaultAuditV1(
                broker_account_id=scope.account_id,
                actor_principal_id=scope.principal_id,
                event_type="revoked",
                credential_version=row.version,
            )
        )
        session.flush()
        return CredentialVersionInfo(version=row.version, status="revoked")


__all__ = [
    "AwsKmsDataKeyProvider",
    "CredentialInput",
    "CredentialMaterial",
    "CredentialVault",
    "CredentialVaultConflictError",
    "CredentialVaultDisabledError",
    "CredentialVaultError",
    "CredentialVaultInputError",
    "CredentialVaultIntegrityError",
    "CredentialVaultUnavailableError",
    "CredentialVersionInfo",
    "DataKeyProvider",
    "valid_aws_kms_key_arn",
    "valid_aws_region",
]
