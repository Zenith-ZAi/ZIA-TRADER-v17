from __future__ import annotations

import hashlib
import json
import struct

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn import verify_authentication_response
from webauthn.helpers.exceptions import InvalidAuthenticationResponse


def b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_assertion(private_key, challenge: bytes, *, origin="https://login.example.com", rp_id="login.example.com", count=1):
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    del decode_dss_signature  # Keep the generated DER ECDSA signature as WebAuthn requires.
    client_data = json.dumps({
        "type": "webauthn.get", "challenge": b64url(challenge), "origin": origin,
    }, separators=(",", ":")).encode()
    auth_data = hashlib.sha256(rp_id.encode()).digest() + b"\x05" + struct.pack(">I", count)
    signed = auth_data + hashlib.sha256(client_data).digest()
    signature = private_key.sign(signed, ec.ECDSA(hashes.SHA256()))
    credential_id = b"credential-id-0001"
    response = {
        "id": b64url(credential_id),
        "rawId": b64url(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": b64url(client_data),
            "authenticatorData": b64url(auth_data),
            "signature": b64url(signature),
            "userHandle": None,
        },
    }
    numbers = private_key.public_key().public_numbers()
    cose_key = cbor2.dumps({
        1: 2, 3: -7, -1: 1,
        -2: numbers.x.to_bytes(32, "big"),
        -3: numbers.y.to_bytes(32, "big"),
    })
    return response, cose_key, credential_id


def test_pinned_library_authentication_verifies_real_es256_and_rejects_origin_rp_signature_and_counter():
    private_key = ec.generate_private_key(ec.SECP256R1())
    challenge = b"server-generated-challenge-bytes-32"
    response, cose_key, credential_id = make_assertion(private_key, challenge)
    verified = verify_authentication_response(
        credential=response,
        expected_challenge=challenge,
        expected_rp_id="login.example.com",
        expected_origin=["https://login.example.com"],
        credential_public_key=cose_key,
        credential_current_sign_count=0,
        require_user_verification=True,
    )
    assert verified.credential_id == credential_id
    assert verified.new_sign_count == 1
    assert verified.user_verified is True

    with pytest.raises(InvalidAuthenticationResponse, match="origin"):
        verify_authentication_response(
            credential=response, expected_challenge=challenge, expected_rp_id="login.example.com",
            expected_origin=["https://evil.example.com"], credential_public_key=cose_key,
            credential_current_sign_count=0, require_user_verification=True,
        )
    with pytest.raises(InvalidAuthenticationResponse, match="RP ID"):
        verify_authentication_response(
            credential=response, expected_challenge=challenge, expected_rp_id="evil.example.com",
            expected_origin=["https://login.example.com"], credential_public_key=cose_key,
            credential_current_sign_count=0, require_user_verification=True,
        )

    broken = json.loads(json.dumps(response))
    broken["response"]["signature"] = b64url(b"invalid-signature")
    with pytest.raises(InvalidAuthenticationResponse, match="signature"):
        verify_authentication_response(
            credential=broken, expected_challenge=challenge, expected_rp_id="login.example.com",
            expected_origin=["https://login.example.com"], credential_public_key=cose_key,
            credential_current_sign_count=0, require_user_verification=True,
        )

    replay, _, _ = make_assertion(private_key, b"another-fresh-challenge-value-0001", count=1)
    with pytest.raises(InvalidAuthenticationResponse, match="sign count"):
        verify_authentication_response(
            credential=replay, expected_challenge=b"another-fresh-challenge-value-0001",
            expected_rp_id="login.example.com", expected_origin=["https://login.example.com"],
            credential_public_key=cose_key, credential_current_sign_count=1,
            require_user_verification=True,
        )
