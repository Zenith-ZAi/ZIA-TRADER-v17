from fastapi.testclient import TestClient

from main import app


def _token(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/token",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_current_user_does_not_expose_password():
    with TestClient(app) as client:
        token = _token(client, "admin", "admin")
        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"username": "admin", "roles": ["admin", "trader"]}
    assert "password" not in payload


def test_admin_dashboard_requires_admin_role():
    with TestClient(app) as client:
        token = _token(client, "user", "password")
        response = client.get(
            "/admin/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403