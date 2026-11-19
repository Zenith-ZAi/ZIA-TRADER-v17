"""Metadata-only catalog for market, news, and execution integrations.

The catalog is deliberately not a credential store and is not a health check. It
contains provider identifiers, capability status, names of Settings fields that
would be consulted, and a conservative ``configured`` boolean. Secret values,
provider URLs, account identifiers, and entitlement/health claims never belong
in this response.
"""

from __future__ import annotations

from typing import Any

from config.settings import Settings
from core.market_data_collector import UnifiedMarketDataCollector


_SIMULATED_BINANCE_MODES = {"simulated", "simulation", "mock"}


# IDs are namespaced so that the same upstream (for example Alpha Vantage) can
# appear in its distinct market-data and news roles without ambiguity.
_PROVIDER_METADATA: tuple[dict[str, Any], ...] = (
    # News and trend providers.
    {
        "id": "news:rss",
        "name": "rss",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": [],
    },
    {
        "id": "news:gdelt",
        "name": "gdelt",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": [],
    },
    {
        "id": "news:coingecko",
        "name": "coingecko",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["COINGECKO_API_KEY"],
    },
    {
        "id": "news:alpha_vantage",
        "name": "alpha_vantage",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["ALPHA_VANTAGE_API_KEY"],
    },
    {
        "id": "news:marketaux",
        "name": "marketaux",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["MARKETAUX_API_KEY"],
    },
    {
        "id": "news:finnhub",
        "name": "finnhub",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["FINNHUB_API_KEY"],
    },
    {
        "id": "news:twelve_data",
        "name": "twelve_data",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["TWELVE_DATA_API_KEY"],
    },
    {
        "id": "news:benzinga",
        "name": "benzinga",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["BENZINGA_API_KEY"],
    },
    {
        "id": "news:benzinga_trends",
        "name": "benzinga_trends",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["BENZINGA_API_KEY"],
    },
    {
        "id": "news:newsapi",
        "name": "newsapi",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["NEWSAPI_API_KEY"],
    },
    {
        "id": "news:cryptopanic",
        "name": "cryptopanic",
        "kind": "news",
        "capability": "implemented",
        "credential_setting_names": ["CRYPTOPANIC_API_KEY"],
    },
    # Execution/data connectors. Live submission remains blocked by design.
    {
        "id": "execution:binance_simulated",
        "name": "binance_simulated",
        "kind": "execution",
        "capability": "implemented",
        "credential_setting_names": [],
    },
    {
        "id": "execution:binance_testnet",
        "name": "binance_testnet",
        "kind": "execution",
        "capability": "implemented",
        "credential_setting_names": ["BINANCE_API_KEY", "BINANCE_SECRET_KEY"],
    },
    {
        "id": "execution:binance_live",
        "name": "binance_live",
        "kind": "execution",
        "capability": "blocked",
        "credential_setting_names": ["BINANCE_API_KEY", "BINANCE_SECRET_KEY"],
    },
    {
        "id": "execution:ccxt",
        "name": "ccxt",
        "kind": "execution",
        "capability": "blocked",
        "credential_setting_names": ["BINANCE_API_KEY", "BINANCE_SECRET_KEY"],
    },
    {
        "id": "execution:mt5",
        "name": "mt5",
        "kind": "execution",
        "capability": "blocked",
        "credential_setting_names": [],
    },
    {
        "id": "execution:forex_paper",
        "name": "forex_paper",
        "kind": "execution",
        "capability": "implemented",
        "credential_setting_names": [],
    },
    {
        "id": "execution:forex_live",
        "name": "forex_live",
        "kind": "execution",
        "capability": "blocked",
        "credential_setting_names": [],
    },
    {
        "id": "execution:fix",
        "name": "fix",
        "kind": "execution",
        "capability": "blocked",
        "credential_setting_names": [],
    },
)


def _has_all_settings(settings: Settings, names: list[str]) -> bool:
    """Check presence only; never return or log the setting values."""
    return all(bool(getattr(settings, name, None)) for name in names)


def _selected_execution(settings: Settings, name: str) -> bool:
    adapter = str(getattr(settings, "MARKET_ADAPTER", "binance")).strip().lower()
    market_type = str(getattr(settings, "MARKET_TYPE", "spot")).strip().lower()
    mode = str(getattr(settings, "BINANCE_MODE", "simulated")).strip().lower()
    forex_mode = str(getattr(settings, "FOREX_MODE", "paper")).strip().lower()

    if name == "binance_simulated":
        return adapter == "binance" and mode in _SIMULATED_BINANCE_MODES
    if name == "binance_testnet":
        return adapter == "binance" and mode == "testnet"
    if name == "binance_live":
        # This item is metadata for an intentionally blocked capability; do not
        # infer or advertise live readiness from keys or flags.
        return False
    if name == "ccxt":
        return adapter == "ccxt" or (adapter == "binance" and market_type == "futures")
    if name == "mt5":
        return adapter == "mt5"
    if name == "forex_paper":
        return adapter in {"forex", "fx"} and forex_mode == "paper"
    if name == "forex_live":
        return adapter in {"forex", "fx"} and forex_mode == "live"
    if name == "fix":
        return adapter == "fix"
    return False


def _configured(settings: Settings, entry: dict[str, Any]) -> bool:
    name = str(entry["name"])
    kind = str(entry["kind"])
    capability = str(entry["capability"])
    if capability == "blocked":
        return False
    if kind == "execution":
        selected = _selected_execution(settings, name)
        return selected and _has_all_settings(settings, entry["credential_setting_names"])
    if kind == "market_data":
        enabled_flag = {"binance_public": "MARKET_DATA_BINANCE_PUBLIC_ENABLED", "alpha_vantage": "MARKET_DATA_ALPHA_VANTAGE_ENABLED"}.get(name)
        return bool(getattr(settings, "MARKET_DATA_INGESTION_ENABLED", False) and enabled_flag
                    and getattr(settings, enabled_flag, False) and _has_all_settings(settings, entry["credential_setting_names"]))
    if name in {"rss", "gdelt"}:
        return True  # Public contextual paths do not require a key.
    if name == "coingecko":
        pro_host = settings.COINGECKO_BASE_URL.startswith("https://pro-api.coingecko.com/")
        return not pro_host or ("coingecko" in settings.NEWS_ENABLED_KEYED_PROVIDERS and bool(settings.COINGECKO_API_KEY))
    keyed_name = "benzinga" if name == "benzinga_trends" else name
    return keyed_name in settings.NEWS_ENABLED_KEYED_PROVIDERS and _has_all_settings(settings, entry["credential_setting_names"])



def build_provider_catalog(settings: Settings) -> list[dict[str, Any]]:
    """Return safe metadata for every implemented or intentionally blocked path."""
    # Reuse the existing ingestion catalog: CoinGecko is context, not exchange OHLCV.
    market_entries = [
        {"id": f"market_data:{name}", "name": name, "kind": "market_data",
         "capability": "implemented" if info["status"].startswith("available_when") else "blocked",
         "credential_setting_names": ["ALPHA_VANTAGE_API_KEY"] if name == "alpha_vantage" else []}
        for name, info in UnifiedMarketDataCollector.catalog().items()
    ]
    catalog: list[dict[str, Any]] = []
    for raw in [*market_entries, *_PROVIDER_METADATA]:
        entry = dict(raw)
        entry["credential_setting_names"] = list(entry["credential_setting_names"])
        entry["configured"] = _configured(settings, entry)
        catalog.append(entry)
    return catalog


# Short alias for callers that prefer a noun matching the endpoint name.
def provider_catalog(settings: Settings) -> list[dict[str, Any]]:
    return build_provider_catalog(settings)
