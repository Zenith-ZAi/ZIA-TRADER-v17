from api.dependencies import auth_users
from config.settings import Settings


def test_demo_auth_is_disabled_and_credentials_are_empty_by_default(monkeypatch):
    for name in (
        "DEMO_AUTH_ENABLED",
        "DEMO_USER_PASSWORD",
        "DEMO_ADMIN_PASSWORD",
        "AUTH_MODE",
        "AUTH_USERNAME",
        "AUTH_PASSWORD",
        "ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.DEMO_AUTH_ENABLED is False
    assert settings.DEMO_USER_PASSWORD == ""
    assert settings.DEMO_ADMIN_PASSWORD == ""
    assert auth_users(settings) == {}


def test_demo_auth_requires_each_password_to_be_explicitly_configured():
    settings = Settings(
        DEMO_AUTH_ENABLED=True,
        DEMO_USER_PASSWORD="",
        DEMO_ADMIN_PASSWORD="explicit-test-admin-secret",
        AUTH_MODE="demo",
        ENVIRONMENT="development",
    )

    assert auth_users(settings) == {
        "admin": {
            "username": "admin",
            "password": "explicit-test-admin-secret",
            "roles": ["admin", "trader"],
        }
    }
