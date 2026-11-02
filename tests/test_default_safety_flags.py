from config.settings import Settings


def test_execution_defaults_are_fail_closed(monkeypatch):
    for name in (
        "LIVE_TRADING_ENABLED",
        "LIVE_MODE",
        "LIVE_KILL_SWITCH",
        "AUTONOMOUS_TRADING_ENABLED",
        "MANUAL_TRADING_ENABLED",
        "AUTO_START_ENGINES",
        "NEURAL_MODELS_ENABLED",
        "SHADOW_MODE_ENABLED",
        "ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.LIVE_MODE is False
    assert settings.LIVE_KILL_SWITCH is True
    assert settings.AUTONOMOUS_TRADING_ENABLED is False
    assert settings.MANUAL_TRADING_ENABLED is False
    assert settings.AUTO_START_ENGINES is False
    assert settings.NEURAL_MODELS_ENABLED is False
    assert settings.SHADOW_MODE_ENABLED is True
