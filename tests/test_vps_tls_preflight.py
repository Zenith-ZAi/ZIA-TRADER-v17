from __future__ import annotations

import ssl
from pathlib import Path

import yaml

from scripts import vps_preflight


class FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeTLSConnection(FakeSocket):
    def version(self):
        return "TLSv1.3"


class VerifiedContext:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def __init__(self):
        self.server_hostname = None

    def wrap_socket(self, raw, *, server_hostname):
        self.server_hostname = server_hostname
        return FakeTLSConnection()


def test_tls_probe_connects_to_compose_nginx_but_validates_certificate_hostname(monkeypatch):
    context = VerifiedContext()
    connections = []
    monkeypatch.setattr(vps_preflight.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(
        vps_preflight.socket,
        "create_connection",
        lambda address, **kwargs: connections.append((address, kwargs)) or FakeSocket(),
    )

    passed, detail = vps_preflight._probe_tls_endpoint(
        "https://trader.example.test/", connect_host="nginx"
    )

    assert passed is True
    assert detail == "TLSv1.3"
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.server_hostname == "trader.example.test"
    assert connections == [(("nginx", 443), {"timeout": 3})]


def test_tls_probe_defaults_tcp_target_to_certificate_hostname(monkeypatch):
    context = VerifiedContext()
    connections = []
    monkeypatch.setattr(vps_preflight.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(
        vps_preflight.socket,
        "create_connection",
        lambda address, **kwargs: connections.append((address, kwargs)) or FakeSocket(),
    )

    passed, _detail = vps_preflight._probe_tls_endpoint("https://proxy.example.test:8443/")

    assert passed is True
    assert connections[0][0] == ("proxy.example.test", 8443)
    assert context.server_hostname == "proxy.example.test"


def test_tls_probe_rejects_non_https_url_without_connecting(monkeypatch):
    calls = []
    monkeypatch.setattr(
        vps_preflight.socket,
        "create_connection",
        lambda *args, **kwargs: calls.append(args),
    )

    passed, detail = vps_preflight._probe_tls_endpoint("http://proxy.example.test/")

    assert passed is False
    assert detail.startswith("falha:")
    assert calls == []


def test_vps_compose_passes_tls_probe_settings_without_mounting_private_key_in_api():
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.vps.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    api_environment = api["environment"]
    api_volumes = api.get("volumes", [])
    nginx_volumes = compose["services"]["nginx"]["volumes"]

    assert api_environment["REQUIRE_TLS_PROXY"] == "${REQUIRE_TLS_PROXY:-false}"
    assert api_environment["TLS_PREFLIGHT_URL"] == "${TLS_PREFLIGHT_URL:-}"
    assert api_environment["TLS_PREFLIGHT_CONNECT_HOST"] == "${TLS_PREFLIGHT_CONNECT_HOST:-nginx}"
    assert all("deploy/tls" not in str(volume) for volume in api_volumes)
    assert "./deploy/tls:/etc/nginx/certs:ro" in nginx_volumes
