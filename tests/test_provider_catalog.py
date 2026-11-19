from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.application import create_app
from config.settings import Settings
from core.provider_catalog import build_provider_catalog


TEST_SECRET = "catalog-test-secret-value"


class FakeRuntime:
    async def close(self) -> None:
        return None


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ENVIRONMENT": "development",
        "AUTH_MODE": "demo",
        "DEMO_AUTH_ENABLED": True,
        "DEMO_USER_PASSWORD": "catalog-user-password",
        "DEMO_ADMIN_PASSWORD": "catalog-admin-password",
        "SECRET_KEY": TEST_SECRET,
        "LIVE_TRADING_ENABLED": False,
        "LIVE_MODE": False,
        "LIVE_KILL_SWITCH": True,
        "BINANCE_MODE": "simulated",
        "AUTO_START_ENGINES": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _app(settings: Settings):
    async def runtime_builder(_settings: Settings) -> FakeRuntime:
        return FakeRuntime()

    return create_app(settings, runtime_builder=runtime_builder)


def test_catalog_is_metadata_only_and_never_contains_secret_values_or_urls():
    settings = _settings(
        ALPHA_VANTAGE_API_KEY="catalog-alpha-key",
        BINANCE_API_KEY="catalog-binance-key",
        BINANCE_SECRET_KEY="catalog-binance-secret",
    )

    catalog = build_provider_catalog(settings)

    assert catalog
    assert all(set(item) == {"id", "name", "kind", "capability", "credential_setting_names", "configured"} for item in catalog)
    assert all(isinstance(item["configured"], bool) for item in catalog)
    assert all(isinstance(item["credential_setting_names"], list) for item in catalog)
    assert not any("url" in key.lower() or "endpoint" in key.lower() for item in catalog for key in item)
    serialized = repr(catalog)
    assert "catalog-alpha-key" not in serialized
    assert "catalog-binance-key" not in serialized
    assert "catalog-binance-secret" not in serialized

    by_id = {item["id"]: item for item in catalog}
    assert by_id["execution:binance_simulated"]["capability"] == "implemented"
    assert by_id["execution:binance_live"]["capability"] == "blocked"
    assert by_id["execution:binance_live"]["configured"] is False
    assert by_id["news:alpha_vantage"]["credential_setting_names"] == ["ALPHA_VANTAGE_API_KEY"]


def test_catalog_route_requires_authentication():
    app = _app(_settings())
    with TestClient(app) as client:
        response = client.get("/integrations/catalog")
    assert response.status_code == 401


def test_catalog_route_rejects_authenticated_trader():
    app = _app(_settings())
    with TestClient(app) as client:
        token_response = client.post(
            "/token",
            data={"username": "user", "password": "catalog-user-password"},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]
        response = client.get(
            "/integrations/catalog",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


def test_catalog_route_allows_authenticated_admin_without_runtime_dependency():
    settings = _settings(
        ALPHA_VANTAGE_API_KEY="catalog-alpha-key",
        BINANCE_API_KEY="catalog-binance-key",
        BINANCE_SECRET_KEY="catalog-binance-secret",
    )
    app = _app(settings)

    with TestClient(app) as client:
        token_response = client.post(
            "/token",
            data={"username": "admin", "password": "catalog-admin-password"},
        )
        assert token_response.status_code == 200
        token = token_response.json()["access_token"]
        response = client.get(
            "/integrations/catalog",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"providers"}
    assert payload["providers"]
    assert "catalog-alpha-key" not in response.text
    assert "catalog-binance-key" not in response.text
    assert "catalog-binance-secret" not in response.text
    assert all("url" not in item and "endpoint" not in item for item in payload["providers"])


def test_catalog_respects_market_ingestion_gate_and_does_not_promote_context_to_candles():
    settings = _settings(MARKET_DATA_INGESTION_ENABLED=False, MARKET_DATA_BINANCE_PUBLIC_ENABLED=True,
                         MARKETAUX_API_KEY="dummy-key", NEWS_ENABLED_KEYED_PROVIDERS=[])
    by_id = {item["id"]: item for item in build_provider_catalog(settings)}
    assert by_id["market_data:binance_public"]["configured"] is False
    assert by_id["market_data:coingecko"]["capability"] == "blocked"
    assert by_id["news:coingecko"]["capability"] == "implemented"
    assert by_id["news:marketaux"]["configured"] is False
    settings.NEWS_ENABLED_KEYED_PROVIDERS = ["marketaux"]
    by_id = {item["id"]: item for item in build_provider_catalog(settings)}
    assert by_id["news:marketaux"]["configured"] is True
