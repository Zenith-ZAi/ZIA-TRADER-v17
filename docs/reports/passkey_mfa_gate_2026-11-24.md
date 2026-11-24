# Gate MFA/Passkey — 2026-11-24

**Branch:** `feature/gate-passkey-auth`, based on the assigned checkout. **Status:** implementation candidate; review/CI and browser/frontend acceptance remain pending. This report does not mark the passkey gate, any item in the 16-gate progress snapshot, or operational readiness as accepted.

## Scope delivered

The existing `/token` password endpoint and `auth_users` identity source are reused. With `PASSKEY_MFA_REQUIRED=false` (default), password login continues returning the legacy access token. When the flag is true, successful password login returns only a short-lived `preauth_token` (`token_use=passkey_preauth`, one narrow scope, five-minute expiry) and a `next` action; it does not return `access_token`. Existing protected HTTP dependencies reject JWTs without `mfa_verified=true` while this mode is enabled. A final access token is issued only after the WebAuthn assertion verifier succeeds and has `mfa_verified=true`.

The JSON WebAuthn endpoints are:

| Endpoint | Purpose / authorization |
|---|---|
| `POST /passkey/registration/options` | Authenticated password session or narrowly scoped first-enrollment preauth; bootstrap flag required; first credential only. |
| `POST /passkey/registration/verify` | Same enrollment gate; verifies attestation response and persists verified public credential material. |
| `POST /passkey/authentication/options` | Takes configured username; generates discoverable-by-username options restricted to that user's stored credential IDs. |
| `POST /passkey/authentication/verify` | Verifies assertion bound to username and issues the final access token. |

The passkey server configuration is static and explicit: `WEBAUTHN_RP_ID` and comma-separated `WEBAUTHN_ALLOWED_ORIGINS`. Neither `Host`, `Origin`, nor forwarded headers from a request feed WebAuthn verification. Every listed origin must be an exact origin on the RP ID domain; HTTPS is required except for loopback development origins. CORS remains independently configured and must be aligned operationally.

## Persistence and security properties

Alembic revision `e8c4b70d2a91` adds `passkey_credentials` and `passkey_challenges`; the existing SQLite development `create_all` path registers the same SQLAlchemy metadata. Challenges use 32 random bytes, have a five-minute expiry, are bound to normalized username and ceremony, and are deleted conditionally and committed before crypto verification, so concurrent workers share one-time consumption through SQL storage. Storage/configuration errors fail closed.

The credential table stores credential ID, verified public key, sign count, normalized username, transports, creation time and last-use time. It never stores private keys, biometric data, raw credential responses or attestation payloads. This increment deliberately imposes a strict limit of **one credential per configured env-auth user** via a database uniqueness constraint; it cannot be replaced or re-enrolled through the API. Registration/authentication request responses and challenges are not logged by these endpoints.

`webauthn==3.0.1` is pinned in `requirements.txt` and `requirements.lock`. Its root APIs and parameter signatures were inspected from that exact installed release. Registration and assertion verification receive the configured RP ID/origin allowlist and require user presence plus user verification. Assertion verification checks the signature and counter policy; the storage update also uses a compare-and-set condition to reject stale concurrent counter updates. Authenticators that report a zero counter rely on challenge single-use/replay protection, as specified by the library's counter semantics.

## Bootstrap and recovery limits

Both `PASSKEY_MFA_REQUIRED` and `PASSKEY_ENROLLMENT_ENABLED` default to `false`. For a user who has no passkey, controlled bootstrap requires an operator to enable `PASSKEY_ENROLLMENT_ENABLED`, permit that user to establish the existing password-authenticated session (in required-MFA mode the `/token` response is still registration-only preauth), complete registration, then disable enrollment again. Enrollment cannot overwrite an existing credential. If MFA is enabled for a user without a credential while bootstrap is disabled, that user receives only registration-scope preauth and cannot use protected endpoints; plan bootstrap before enabling the MFA requirement.

No self-service recovery, credential revocation, deletion, replacement, or admin recovery endpoint is implemented. Loss of the sole passkey is an account lockout until a separately designed, audited, out-of-band recovery procedure exists; do not delete records or disable MFA without identity verification and operator controls. This feature still authenticates the current env-backed user map; it does not bind `principal_v1`/membership or turn the app into a persistent multi-user identity service.

## WebSocket boundary and remaining risk

Review found that the existing `authenticate_websocket` path accepted password-only/preauth JWTs. This increment now rejects `token_use=passkey_preauth` and, when `PASSKEY_MFA_REQUIRED=true`, requires `mfa_verified` to be the literal boolean `true`; a regression covers both rejected token classes and the verified token. The separate exposure risk remains: `/ws/dashboard` still transports its JWT in the query string, which can leak through access logs, proxies, or telemetry. Do not expose that transport publicly until the WebSocket authentication/transport gate removes query-string tokens and verifies log redaction.

## Validation and acceptance limits

Automated tests cover MFA-off legacy login, no final token after password in required mode, registration-only preauth, first credential enrollment and overwrite rejection, success only after assertion-verifier success, challenge expiration/reuse, account/credential isolation, WebSocket rejection of password-only/preauth tokens when MFA is required, invalid config, and a real ES256 WebAuthn assertion signature generated with a test private key. The pinned library is also exercised against invalid origin, RP ID, signature and non-incrementing sign count. The full repository suite completed with **429 passed, 5 skipped, 0 failed** in 34.10 seconds after synchronizing the temporary venv from `requirements.lock` with the CPU PyTorch backend. All five skips require `TEST_DATABASE_URL`; the repository CI workflow provisions PostgreSQL for those tests. `uv pip check` passed. WebAuthn origin/RP validation follows the relying-party requirements in the W3C specification [1], using the pinned `webauthn` server library [2].

The first full-suite run exposed a stale assertion in the already-accepted client-scope migration test: it upgraded to `head` but expected the earlier revision `c3f1e2a9b7d4`. The test now upgrades directly to that client-scope revision, preserving its intent while allowing later additive migrations; the complete suite then passed. The earlier `ModuleNotFoundError: torch` came only from the incomplete temporary venv and was resolved by syncing the repository lock, with no dependency change needed. This is **not** evidence of frontend or browser interoperability. No real authenticator/browser ceremony, deployed TLS origin, frontend JSON serializer, production PostgreSQL integration, independent security review, or CI result has been accepted here. Do not label passkey ACCEPTED until browser/frontend contract testing and project review/CI succeed. The checklist remains **16 gates, 7 accepted (43.75%)**; the passkey gate is still unaccepted. The updated criteria hash and pending increment are recorded in `docs/progress/zt01_current_2026-11-24.json`. LIVE/manual/autonomy/autostart behavior and exchange/order paths were not changed or enabled.

## References

[1]: https://www.w3.org/TR/webauthn-2/ "W3C Web Authentication Level 2"
[2]: https://pypi.org/project/webauthn/ "Python webauthn server library"
