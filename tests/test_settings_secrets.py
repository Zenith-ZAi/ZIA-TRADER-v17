from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from config.settings import Settings


SENSITIVE_FIELDS = (
    "DEMO_USER_PASSWORD",
    "DEMO_ADMIN_PASSWORD",
    "AUTH_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
    "SECRET_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "BENZINGA_API_KEY",
    "MARKETAUX_API_KEY",
    "FINNHUB_API_KEY",
    "TWELVE_DATA_API_KEY",
    "COINGECKO_API_KEY",
    "NEWSAPI_API_KEY",
    "CRYPTOPANIC_API_KEY",
    "BINANCE_DEMO_API_KEY",
    "BINANCE_DEMO_SECRET_KEY",
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
    "POLYGON_API_KEY",
    "CREDENTIAL_VAULT_KMS_KEY_ARN",
)


def test_sensitive_settings_are_hidden_from_repr_and_model_dump():
    marker = "settings-test-secret-value"
    settings = Settings(
        _env_file=None,
        **{
            field: marker
            for field in SENSITIVE_FIELDS
            if field not in {"DATABASE_URL", "REDIS_URL"}
        },
        DATABASE_URL="postgresql+psycopg2://user:password@db/app",
        REDIS_URL="redis://:password@redis:6379/0",
    )

    rendered = repr(settings)
    dumped = settings.model_dump()
    assert all(Settings.model_fields[field].repr is False for field in SENSITIVE_FIELDS)
    assert all(Settings.model_fields[field].exclude is True for field in SENSITIVE_FIELDS)
    assert marker not in rendered
    assert marker not in repr(dumped)
    assert all(field not in dumped for field in SENSITIVE_FIELDS)


def test_settings_uses_environment_then_dotenv_then_opt_in_secret_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dotenv = tmp_path / "settings.env"
    secrets_dir = tmp_path / "secret-files"
    secrets_dir.mkdir()
    dotenv.write_text(
        "SECRET_KEY=dotenv-secret\nDATABASE_URL=sqlite:///dotenv.db\n",
        encoding="utf-8",
    )
    (secrets_dir / "SECRET_KEY").write_text("secret-file-secret\n", encoding="utf-8")
    (secrets_dir / "DATABASE_URL").write_text("sqlite:///secret-file.db\n", encoding="utf-8")

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from_dotenv = Settings(_env_file=dotenv, _secrets_dir=secrets_dir)
    assert from_dotenv.SECRET_KEY == "dotenv-secret"
    assert from_dotenv.DATABASE_URL == "sqlite:///dotenv.db"

    monkeypatch.setenv("SECRET_KEY", "environment-secret")
    from_environment = Settings(_env_file=dotenv, _secrets_dir=secrets_dir)
    assert from_environment.SECRET_KEY == "environment-secret"

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///environment.db")
    environment_over_dotenv = Settings(_env_file=dotenv, _secrets_dir=secrets_dir)
    assert environment_over_dotenv.DATABASE_URL == "sqlite:///environment.db"


def test_secret_file_source_is_opt_in_and_has_no_default_mount():
    assert Settings.model_config.get("secrets_dir") is None


def test_news_keyed_provider_opt_in_defaults_to_empty_and_normalizes_names():
    assert Settings(_env_file=None).NEWS_ENABLED_KEYED_PROVIDERS == []
    settings = Settings(
        _env_file=None,
        NEWS_ENABLED_KEYED_PROVIDERS=[" Alpha_Vantage ", "marketaux"],
    )
    assert settings.NEWS_ENABLED_KEYED_PROVIDERS == ["alpha_vantage", "marketaux"]


@pytest.mark.parametrize(
    "providers",
    [
        ["unknown_provider"],
        ["alpha_vantage", "alpha_vantage"],
        ["newsapi", "NEWSAPI"],
    ],
)
def test_news_keyed_provider_opt_in_rejects_unknown_or_duplicate_names(providers: list[str]):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, NEWS_ENABLED_KEYED_PROVIDERS=providers)


def test_hide_input_in_errors_is_enabled():
    assert Settings.model_config.get("hide_input_in_errors") is True
