import importlib

from fastapi.testclient import TestClient


def test_demo_login_and_public_user(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("AUTO_START_ENGINES", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEMO_USER_PASSWORD", "password")
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "admin")

    module = importlib.import_module("main")
    with TestClient(module.app) as client:
        health_response = client.get("/healthz")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "ok"

        token_response = client.post(
            "/token",
            data={"username": "admin", "password": "admin"},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]

        user_response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert user_response.status_code == 200
        assert user_response.json() == {
            "username": "admin",
            "roles": ["admin", "trader"],
        }
        assert "password" not in user_response.json()


def test_invalid_demo_login_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api-invalid.db'}")
    monkeypatch.setenv("AUTO_START_ENGINES", "false")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")

    module = importlib.import_module("main")
    with TestClient(module.app) as client:
        response = client.post(
            "/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401


def test_dashboard_control_surface_is_exposed():
    import importlib

    module = importlib.import_module("main")
    paths = {getattr(route, "path", "") for route in module.app.routes}
    assert "/dashboard/status" in paths
    assert "/runtime/reload" in paths
    assert "/ws/dashboard" in paths
    assert "/api/optimize_sharpe" in paths
