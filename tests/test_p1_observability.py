from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware import CorrelationIdMiddleware


def test_correlation_id_is_propagated_without_exposing_authorization():
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Correlation-ID": "test-correlation-001"})
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "test-correlation-001"
        assert "authorization" not in response.text.lower()


def test_alert_rules_and_perimeter_artifacts_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "deploy" / "alert_rules.yml").is_file()
    assert (root / "deploy" / "nginx.conf").is_file()
    assert (root / "scripts" / "setup_firewall.sh").is_file()
    assert (root / "scripts" / "generate_test_tls.sh").is_file()
