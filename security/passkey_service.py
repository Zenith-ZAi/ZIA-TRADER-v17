"""Persistent WebAuthn ceremony primitives; never trusts request Host/Origin headers."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from database import PasskeyChallenge, PasskeyCredential

CHALLENGE_TTL_SECONDS = 300
PREAUTH_TTL_SECONDS = 300
MAX_CREDENTIALS_PER_USER = 1


def normalized_username(username: str) -> str:
    return unicodedata.normalize("NFKC", username.strip()).casefold()


def _valid_domain(value: str) -> bool:
    if value == "localhost":
        return True
    labels = value.split(".")
    return (
        len(labels) >= 2
        and len(value) <= 253
        and all(
            1 <= len(label) <= 63
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is not None
            for label in labels
        )
    )


def webauthn_config(settings: Any) -> tuple[str, list[str]]:
    rp_id = str(getattr(settings, "WEBAUTHN_RP_ID", "") or "").strip().lower().rstrip(".")
    origins = [item.strip() for item in str(getattr(settings, "WEBAUTHN_ALLOWED_ORIGINS", "") or "").split(",") if item.strip()]
    if not rp_id or not origins or not rp_id.isascii() or not _valid_domain(rp_id):
        raise HTTPException(status_code=503, detail="passkey_configuration_unavailable")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            host = (parsed.hostname or "").lower().rstrip(".")
            port = parsed.port
            canonical_origin = f"{parsed.scheme}://{parsed.netloc}"
            secure = parsed.scheme == "https" or (parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"})
            if (
                not secure
                or not host
                or not host.isascii()
                or not _valid_domain(host)
                or parsed.netloc != parsed.netloc.lower()
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or (parsed.scheme == "https" and port == 443)
                or (parsed.scheme == "http" and port == 80)
                or canonical_origin != origin
                or not (host == rp_id or host.endswith("." + rp_id))
            ):
                raise ValueError("invalid origin")
        except (ValueError, TypeError):
            raise HTTPException(status_code=503, detail="passkey_configuration_unavailable") from None
    return rp_id, origins


def session_factory(db_manager: Any):
    factory = getattr(db_manager, "SessionLocal", None)
    if not callable(factory):
        raise HTTPException(status_code=503, detail="passkey_storage_unavailable")
    return factory


def _database_error() -> HTTPException:
    return HTTPException(status_code=503, detail="passkey_storage_unavailable")


def credential_for_user(db_manager: Any, username: str) -> PasskeyCredential | None:
    factory = session_factory(db_manager)
    try:
        with factory() as db:
            return db.scalar(select(PasskeyCredential).where(PasskeyCredential.username == normalized_username(username)))
    except SQLAlchemyError:
        raise _database_error() from None


def credentials_for_user(db_manager: Any, username: str) -> list[PasskeyCredential]:
    factory = session_factory(db_manager)
    try:
        with factory() as db:
            return list(db.scalars(select(PasskeyCredential).where(PasskeyCredential.username == normalized_username(username))).all())
    except SQLAlchemyError:
        raise _database_error() from None


def create_challenge(db_manager: Any, *, username: str, ceremony: str) -> bytes:
    factory = session_factory(db_manager)
    challenge = secrets.token_bytes(32)
    now = datetime.now(timezone.utc)
    row = PasskeyChallenge(
        challenge_hash=hashlib.sha256(challenge).digest(),
        challenge=challenge,
        username=normalized_username(username),
        ceremony=ceremony,
        expires_at=now + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        created_at=now,
    )
    try:
        with factory() as db:
            db.execute(
                delete(PasskeyChallenge)
                .where(PasskeyChallenge.expires_at < now)
                .execution_options(synchronize_session=False)
            )
            db.add(row)
            db.commit()
    except SQLAlchemyError:
        raise _database_error() from None
    return challenge


def consume_challenge(db_manager: Any, *, challenge: bytes, username: str, ceremony: str) -> bytes:
    factory = session_factory(db_manager)
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(challenge).digest()
    try:
        with factory() as db:
            row = db.scalar(
                select(PasskeyChallenge).where(
                    PasskeyChallenge.challenge_hash == digest,
                    PasskeyChallenge.username == normalized_username(username),
                    PasskeyChallenge.ceremony == ceremony,
                    PasskeyChallenge.expires_at > now,
                )
            )
            if row is None:
                raise HTTPException(status_code=400, detail="invalid_or_expired_passkey_challenge")
            expected = bytes(row.challenge)
            result = db.execute(
                delete(PasskeyChallenge).where(
                    PasskeyChallenge.challenge_hash == digest,
                    PasskeyChallenge.username == normalized_username(username),
                    PasskeyChallenge.ceremony == ceremony,
                    PasskeyChallenge.expires_at > now,
                ).execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                db.rollback()
                raise HTTPException(status_code=400, detail="invalid_or_expired_passkey_challenge")
            db.commit()
            return expected
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_error() from None


def registration_options(db_manager: Any, settings: Any, username: str) -> dict[str, Any]:
    rp_id, _ = webauthn_config(settings)
    existing = credentials_for_user(db_manager, username)
    if existing:
        raise HTTPException(status_code=409, detail="passkey_already_enrolled")
    challenge = create_challenge(db_manager, username=username, ceremony="registration")
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=str(getattr(settings, "PROJECT_NAME", "ZIA Trader")),
        user_name=normalized_username(username),
        user_display_name=username,
        user_id=hashlib.sha256(normalized_username(username).encode("utf-8")).digest(),
        challenge=challenge,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return json.loads(options_to_json(options))


def verify_registration(db_manager: Any, settings: Any, username: str, credential: dict[str, Any]) -> None:
    rp_id, origins = webauthn_config(settings)
    if credentials_for_user(db_manager, username):
        raise HTTPException(status_code=409, detail="passkey_already_enrolled")
    try:
        challenge_text = credential.get("response", {}).get("clientDataJSON")
        if not isinstance(challenge_text, str):
            raise ValueError("missing client data")
        raw_client_data = base64url_to_bytes(challenge_text)
        client_data = json.loads(raw_client_data)
        request_challenge = base64url_to_bytes(client_data["challenge"])
        expected_challenge = consume_challenge(
            db_manager, challenge=request_challenge, username=username, ceremony="registration"
        )
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=origins,
            require_user_presence=True,
            require_user_verification=True,
        )
        transports = credential.get("transports") or credential.get("response", {}).get("transports") or []
        allowed_transports = {"ble", "hybrid", "internal", "nfc", "usb", "smart-card", "cable"}
        if not isinstance(transports, list) or len(transports) > 8 or any(not isinstance(item, str) or item.lower() not in allowed_transports for item in transports):
            raise ValueError("invalid transports")
        row = PasskeyCredential(
            credential_id=verified.credential_id,
            username=normalized_username(username),
            public_key=verified.credential_public_key,
            sign_count=int(verified.sign_count),
            transports=[item.lower().strip() for item in transports],
            created_at=datetime.now(timezone.utc),
        )
        factory = session_factory(db_manager)
        with factory() as db:
            db.add(row)
            db.commit()
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(status_code=409, detail="passkey_already_enrolled") from None
    except SQLAlchemyError:
        raise _database_error() from None
    except Exception:
        # Credential responses and underlying crypto errors are intentionally not logged or returned.
        raise HTTPException(status_code=400, detail="invalid_passkey_registration") from None


def authentication_options(db_manager: Any, settings: Any, username: str) -> dict[str, Any]:
    rp_id, _ = webauthn_config(settings)
    creds = credentials_for_user(db_manager, username)
    if not creds:
        raise HTTPException(status_code=401, detail="passkey_authentication_unavailable")
    challenge = create_challenge(db_manager, username=username, ceremony="authentication")
    descriptors = [
        PublicKeyCredentialDescriptor(
            id=bytes(item.credential_id),
            transports=[AuthenticatorTransport(value) for value in item.transports] if item.transports else None,
        )
        for item in creds
    ]
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
        allow_credentials=descriptors,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options))


def verify_authentication(db_manager: Any, settings: Any, username: str, credential: dict[str, Any]) -> bool:
    rp_id, origins = webauthn_config(settings)
    try:
        credential_id = base64url_to_bytes(credential.get("rawId") or credential["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_passkey_authentication") from None
    factory = session_factory(db_manager)
    try:
        with factory() as db:
            stored = db.scalar(select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id))
            if stored is None or stored.username != normalized_username(username):
                raise HTTPException(status_code=401, detail="passkey_authentication_failed")
            try:
                client_data = credential["response"]["clientDataJSON"]
                expected_challenge = consume_challenge(
                    db_manager,
                    challenge=base64url_to_bytes(json.loads(base64url_to_bytes(client_data))["challenge"]),
                    username=username,
                    ceremony="authentication",
                )
                verified = verify_authentication_response(
                    credential=credential,
                    expected_challenge=expected_challenge,
                    expected_rp_id=rp_id,
                    expected_origin=origins,
                    credential_public_key=bytes(stored.public_key),
                    credential_current_sign_count=int(stored.sign_count),
                    require_user_verification=True,
                )
                if verified.credential_id != credential_id:
                    raise ValueError("credential mismatch")
                now = datetime.now(timezone.utc)
                result = db.execute(
                    update(PasskeyCredential)
                    .where(
                        PasskeyCredential.credential_id == credential_id,
                        PasskeyCredential.username == normalized_username(username),
                        PasskeyCredential.sign_count == int(stored.sign_count),
                    )
                    .values(sign_count=int(verified.new_sign_count), last_used_at=now)
                )
                if result.rowcount != 1:
                    db.rollback()
                    raise HTTPException(status_code=401, detail="passkey_authentication_failed")
                db.commit()
                return True
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=401, detail="passkey_authentication_failed") from None
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise _database_error() from None
