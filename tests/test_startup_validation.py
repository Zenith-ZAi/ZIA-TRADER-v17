from __future__ import annotations

import pytest

from config.settings import Settings
from config.startup_validation import (
    production_configuration_errors,
    validate_startup_configuration,
)


def safe_production_settings(**overrides) -> Settings:
    values = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "env",
        "AUTH_USERNAME": "zia-admin",
        "AUTH_PASSWORD": "a-long-random-admin-password",
        "SECRET_KEY": "K" * 48,
        "DEMO_AUTH_ENABLED": False,
        "AUTO_START_ENGINES": False,
        "LIVE_TRADING_ENABLED": False,
        "LIVE_MODE": False,
        "LIVE_KILL_SWITCH": True,
        "AUTONOMOUS_TRADING_ENABLED": False,
        "MANUAL_TRADING_ENABLED": False,
        "NEURAL_MODELS_ENABLED": False,
        "SHADOW_MODE_ENABLED": True,
        "REQUIRE_PERSISTENT_DATABASE": True,
        "REQUIRE_PERSISTENT_REDIS": True,
        "REQUIRE_ALEMBIC_HEAD": True,
        "DATABASE_URL": "postgresql+psycopg2://zia:secret@db:5432/zia",
        "REDIS_URL": "redis://:secret@redis:6379/0",
        "BINANCE_MODE": "simulated",
    }
    values.update(overrides)
    return Settings(**values)


def test_development_settings_are_not_subject_to_production_vps_constraints():
    settings = Settings(ENVIRONMENT="development")
    assert production_configuration_errors(settings) == []


def test_complete_fail_closed_production_configuration_is_accepted():
    validate_startup_configuration(safe_production_settings())


def test_auth_mode_normalization_matches_production_startup_gate():
    from api.dependencies import auth_users

    settings = safe_production_settings(AUTH_MODE=" env ")
    validate_startup_configuration(settings)
    assert auth_users(settings)["zia-admin"]["password"] == "a-long-random-admin-password"


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"SECRET_KEY": "dev-only-change-me"}, "SECRET_KEY"),
        ({"SECRET_KEY": "replace-with-at-least-32-random-bytes"}, "SECRET_KEY"),
        ({"AUTH_PASSWORD": "replace-with-generated-admin-password"}, "AUTH_PASSWORD"),
        ({"LIVE_TRADING_ENABLED": True}, "LIVE_TRADING_ENABLED"),
        ({"AUTO_START_ENGINES": True}, "AUTO_START_ENGINES"),
        ({"REQUIRE_PERSISTENT_DATABASE": False}, "REQUIRE_PERSISTENT_DATABASE"),
        ({"BINANCE_MODE": "mainnet"}, "BINANCE_MODE"),
    ],
)
def test_unsafe_production_configuration_is_rejected(override, expected):
    errors = production_configuration_errors(safe_production_settings(**override))
    assert any(expected in error for error in errors)


def test_validator_error_never_contains_secret_values():
    settings = safe_production_settings(SECRET_KEY="replace-with-this-private-secret")
    with pytest.raises(RuntimeError) as exc_info:
        validate_startup_configuration(settings)
    assert "replace-with-this-private-secret" not in str(exc_info.value)
