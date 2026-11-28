from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from fastapi import HTTPException

from api.application import create_app
from config.settings import Settings
from database import Base, PasskeyCredential, PasskeyChallenge
from database_manager import DatabaseManager
from api.dependencies import authenticate_websocket
from security.jwt_utils import create_access_token


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class Runtime:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.trading_manager = SimpleNamespace()

    async def close(self):
        self.db_manager.engine.dispose()


def app_and_manager(tmp_path, **overrides):
    config = dict(
        ENVIRONMENT="development",
        AUTH_MODE="env",
        AUTH_USERNAME="alice",
        AUTH_PASSWORD="a-long-test-password",
        SECRET_KEY="test-secret-key-material-that-is-long-enough",
        PASSKEY_MFA_REQUIRED=False,
        PASSKEY_ENROLLMENT_ENABLED=False,
        WEBAUTHN_RP_ID="login.example.com",
        WEBAUTHN_ALLOWED_ORIGINS="https://login.example.com",
        AUTO_START_ENGINES=False,
    )
    config.update(overrides)
    settings = Settings(**config)
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'passkey.db'}")
    Base.metadata.create_all(manager.engine)

    async def runtime_builder(_settings):
        return Runtime(manager)

    return create_app(settings, runtime_builder=runtime_builder), manager


def test_password_login_default_off_remains_final_token(tmp_path):
    app, _manager = app_and_manager(tmp_path)
    with TestClient(app) as client:
        response = client.post("/token", data={"username": "alice", "password": "a-long-test-password"})
        assert response.status_code == 200
        assert "access_token" in response.json()
        assert "preauth_token" not in response.json()
        profile = client.get("/users/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"})
        assert profile.status_code == 200


def test_required_mfa_enrollment_then_authentication_only_finalizes_after_passkey(tmp_path, monkeypatch):
    import security.passkey_service as service

    app, manager = app_and_manager(
        tmp_path,
        PASSKEY_MFA_REQUIRED=True,
        PASSKEY_ENROLLMENT_ENABLED=True,
    )
    with TestClient(app) as client:
        first_login = client.post("/token", data={"username": "alice", "password": "a-long-test-password"})
        assert first_login.status_code == 200
        first = first_login.json()
        assert first["next"] == "passkey_registration"
        assert "access_token" not in first
        preauth = first["preauth_token"]
        assert client.get("/users/me", headers={"Authorization": f"Bearer {preauth}"}).status_code == 401
        headers = {"Authorization": f"Bearer {preauth}"}
        options = client.post("/passkey/registration/options", headers=headers, json={})
        assert options.status_code == 200
        registration_options = options.json()
        assert registration_options["rp"]["id"] == "login.example.com"
        client_data = b64url(json.dumps({
            "type": "webauthn.create",
            "challenge": registration_options["challenge"],
            "origin": "https://login.example.com",
        }).encode())
        monkeypatch.setattr(service, "verify_registration_response", lambda **_kwargs: SimpleNamespace(
            credential_id=b"alice-credential-id",
            credential_public_key=b"fake-public-cose-key",
            sign_count=0,
        ))
        registered = client.post(
            "/passkey/registration/verify",
            headers=headers,
            json={"credential": {"id": b64url(b"alice-credential-id"), "transports": ["internal"],
                                 "response": {"clientDataJSON": client_data, "attestationObject": "AA"}}},
        )
        assert registered.status_code == 200, registered.text
        assert registered.json() == {"registered": True}
        # A second enrollment cannot overwrite the existing credential.
        assert client.post("/passkey/registration/options", headers=headers, json={}).status_code == 409

        second_login = client.post("/token", data={"username": "alice", "password": "a-long-test-password"})
        assert second_login.status_code == 200
        assert second_login.json()["next"] == "passkey_authentication"
        second = second_login.json()
        assert "access_token" not in second
        auth_headers = {"Authorization": f"Bearer {second['preauth_token']}"}
        assert client.post("/passkey/authentication/options", json={"username": "alice"}).status_code == 401
        assert client.post(
            "/passkey/authentication/options", headers=headers, json={"username": "alice"}
        ).status_code == 401
        assert client.post(
            "/passkey/authentication/options", headers=auth_headers, json={"username": "bob"}
        ).status_code == 401
        auth_options = client.post(
            "/passkey/authentication/options", headers=auth_headers, json={"username": "ALICE"}
        )
        assert auth_options.status_code == 200
        assert auth_options.json()["rpId"] == "login.example.com"
        challenge_text = auth_options.json()["challenge"]
        auth_client_data = b64url(json.dumps({
            "type": "webauthn.get", "challenge": challenge_text, "origin": "https://login.example.com"
        }).encode())
        assertion = {"id": b64url(b"alice-credential-id"), "rawId": b64url(b"alice-credential-id"),
                     "type": "public-key", "response": {"clientDataJSON": auth_client_data,
                     "authenticatorData": "AA", "signature": "AA", "userHandle": None}}
        # An invalid cryptographic result consumes the challenge and must never create an access token.
        monkeypatch.setattr(service, "verify_authentication_response", lambda **_kwargs: (_ for _ in ()).throw(ValueError()))
        bad = client.post(
            "/passkey/authentication/verify",
            headers=auth_headers,
            json={"username": "alice", "credential": assertion},
        )
        assert bad.status_code == 401
        assert "access_token" not in bad.json()

        # A fresh assertion verified by the pinned library boundary is the only final-token path.
        auth_options = client.post(
            "/passkey/authentication/options", headers=auth_headers, json={"username": "alice"}
        ).json()
        auth_client_data = b64url(json.dumps({
            "type": "webauthn.get", "challenge": auth_options["challenge"], "origin": "https://login.example.com"
        }).encode())
        assertion["response"]["clientDataJSON"] = auth_client_data
        monkeypatch.setattr(service, "verify_authentication_response", lambda **_kwargs: SimpleNamespace(
            credential_id=b"alice-credential-id", new_sign_count=0
        ))
        verified = client.post(
            "/passkey/authentication/verify",
            headers=auth_headers,
            json={"username": "alice", "credential": assertion},
        )
        assert verified.status_code == 200, verified.text
        final_token = verified.json()["access_token"]
        assert client.get("/users/me", headers={"Authorization": f"Bearer {final_token}"}).status_code == 200
        replayed = client.post(
            "/passkey/authentication/verify",
            headers=auth_headers,
            json={"username": "alice", "credential": assertion},
        )
        assert replayed.status_code in {400, 401}


def test_challenges_expire_and_are_consumed_once(tmp_path):
    from security.passkey_service import consume_challenge, create_challenge

    _app, manager = app_and_manager(tmp_path)
    challenge = create_challenge(manager, username="Alice", ceremony="authentication")
    assert consume_challenge(manager, challenge=challenge, username="ALICE", ceremony="authentication") == challenge
    with pytest.raises(HTTPException):
        consume_challenge(manager, challenge=challenge, username="alice", ceremony="authentication")
    expired = create_challenge(manager, username="alice", ceremony="registration")
    factory = manager.SessionLocal
    with factory() as db:
        db.execute(update(PasskeyChallenge).values(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc)))
        db.commit()
    with pytest.raises(HTTPException):
        consume_challenge(manager, challenge=expired, username="alice", ceremony="registration")


def test_passkey_credential_isolation_rejects_other_users(tmp_path, monkeypatch):
    import security.passkey_service as service

    app, manager = app_and_manager(tmp_path, AUTH_USERNAME="alice", PASSKEY_MFA_REQUIRED=True)
    with manager.SessionLocal() as db:
        db.add_all([
            PasskeyCredential(credential_id=b"alice-id", username="alice", public_key=b"alice-key", sign_count=0, transports=[]),
            PasskeyCredential(credential_id=b"bob-id", username="bob", public_key=b"bob-key", sign_count=0, transports=[]),
        ])
        db.commit()
    called = False
    def forbidden(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("credential from another user must be rejected before cryptographic verification")
    monkeypatch.setattr(service, "verify_authentication_response", forbidden)
    with TestClient(app) as client:
        login = client.post("/token", data={"username": "alice", "password": "a-long-test-password"})
        assert login.status_code == 200
        auth_headers = {"Authorization": f"Bearer {login.json()['preauth_token']}"}
        opts = client.post(
            "/passkey/authentication/options", headers=auth_headers, json={"username": "alice"}
        )
        assert opts.status_code == 200
        credential = {"id": b64url(b"bob-id"), "rawId": b64url(b"bob-id"), "type": "public-key",
                      "response": {"clientDataJSON": "e30", "authenticatorData": "AA", "signature": "AA"}}
        result = client.post(
            "/passkey/authentication/verify",
            headers=auth_headers,
            json={"username": "alice", "credential": credential},
        )
        assert result.status_code == 401
        assert called is False


def test_webauthn_config_rejects_untrusted_or_invalid_origins(tmp_path):
    from security.passkey_service import webauthn_config

    settings = Settings(WEBAUTHN_RP_ID="example.com", WEBAUTHN_ALLOWED_ORIGINS="https://evil.example")
    with pytest.raises(HTTPException):
        webauthn_config(settings)


def test_required_mfa_fails_closed_when_persistent_storage_is_missing():
    settings = Settings(
        ENVIRONMENT="development", AUTH_MODE="env", AUTH_USERNAME="alice",
        AUTH_PASSWORD="a-long-test-password", SECRET_KEY="test-secret-key-material-that-is-long-enough",
        PASSKEY_MFA_REQUIRED=True, PASSKEY_ENROLLMENT_ENABLED=True,
        WEBAUTHN_RP_ID="login.example.com", WEBAUTHN_ALLOWED_ORIGINS="https://login.example.com",
    )

    class RuntimeWithoutStorage:
        trading_manager = SimpleNamespace()
        db_manager = None
        async def close(self):
            return None

    async def runtime_builder(_settings):
        return RuntimeWithoutStorage()

    with TestClient(create_app(settings, runtime_builder=runtime_builder)) as client:
        response = client.post("/token", data={"username": "alice", "password": "a-long-test-password"})
        assert response.status_code == 503
        assert response.json()["detail"] == "passkey_storage_unavailable"
        assert "access_token" not in response.json()


def test_required_mfa_rejects_password_only_and_preauth_websocket_tokens(tmp_path):
    from types import SimpleNamespace

    app, _manager = app_and_manager(tmp_path, PASSKEY_MFA_REQUIRED=True)
    settings = app.state.settings
    websocket = SimpleNamespace(
        query_params={},
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
    )

    for claims in (
        {"sub": "alice", "mfa_verified": False},
        {"sub": "alice", "mfa_verified": False, "token_use": "passkey_preauth"},
        {"sub": "alice", "mfa_verified": "true"},
    ):
        websocket.query_params = {
            "token": create_access_token(
                claims,
                secret_key=settings.SECRET_KEY,
                algorithm=settings.ALGORITHM,
            )
        }
        with pytest.raises(HTTPException) as raised:
            authenticate_websocket(websocket)
        assert raised.value.status_code == 401

    websocket.query_params = {
        "token": create_access_token(
            {"sub": "alice", "mfa_verified": True},
            secret_key=settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
    }
    assert authenticate_websocket(websocket)["username"] == "alice"
