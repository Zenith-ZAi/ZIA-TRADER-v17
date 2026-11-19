"""Read-only, multi-provider market-data ingestion isolated from trading decisions."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from infra.async_http import AsyncProviderHTTP

ASSET_CLASSES = {"crypto", "equity", "forex"}
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
KNOWN_PROVIDERS = {"binance_public", "alpha_vantage", "coingecko", "yahoo_chart"}
CRYPTO_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "USD", "BTC", "ETH", "BNB", "EUR", "TRY")

PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "binance_public": {
        "asset_classes": ["crypto"],
        "credential_mode": "none_public_market_data_only",
        "timeframes": sorted(TIMEFRAMES),
        "role": "exchange_ohlcv",
        "execution_grade": False,
        "status": "available_when_opted_in",
    },
    "alpha_vantage": {
        "asset_classes": ["equity", "forex"],
        "credential_mode": "api_key_read_only_market_data",
        "timeframes": ["1d"],
        "role": "daily_reference_ohlcv",
        "execution_grade": False,
        "status": "available_when_key_and_opt_in_are_configured",
    },
    "coingecko": {
        "asset_classes": ["crypto"],
        "credential_mode": "optional_api_key_market_context",
        "timeframes": [],
        "role": "aggregate_market_context_not_exchange_ohlcv",
        "execution_grade": False,
        "status": "not_a_candle_provider_for_this_endpoint",
    },
    "yahoo_chart": {
        "asset_classes": ["crypto", "equity", "forex"],
        "credential_mode": "unofficial_public_endpoint",
        "timeframes": [],
        "role": "not_enabled_for_automated_ingestion",
        "execution_grade": False,
        "status": "blocked_pending_provider_authorization_and_terms_review",
    },
}


class MarketDataCollectionError(ValueError):
    """A request or upstream response cannot be safely ingested."""


class ProviderCollectionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_symbol(asset_class: str, raw_symbol: str) -> str:
    value = str(raw_symbol or "").strip().upper()
    if not value or len(value) > 32:
        raise MarketDataCollectionError("invalid_symbol")
    if asset_class == "crypto":
        compact = re.sub(r"[\s/_-]", "", value)
        if "/" in value or "-" in value or "_" in value:
            parts = re.split(r"[/_-]", value)
            if len(parts) != 2 or not all(parts):
                raise MarketDataCollectionError("invalid_crypto_symbol")
            base, quote = parts
        else:
            pair = next((quote for quote in CRYPTO_QUOTES if compact.endswith(quote) and len(compact) > len(quote)), None)
            if pair is None:
                raise MarketDataCollectionError("crypto_quote_currency_required")
            base, quote = compact[: -len(pair)], pair
        if not re.fullmatch(r"[A-Z0-9]{2,16}", base) or quote not in CRYPTO_QUOTES:
            raise MarketDataCollectionError("invalid_crypto_symbol")
        return f"{base}/{quote}"
    if asset_class == "forex":
        compact = re.sub(r"[\s/_-]", "", value)
        if not re.fullmatch(r"[A-Z]{6}", compact):
            raise MarketDataCollectionError("invalid_forex_symbol")
        return f"{compact[:3]}/{compact[3:]}"
    if asset_class == "equity":
        if not re.fullmatch(r"[A-Z0-9.^_-]{1,32}", value):
            raise MarketDataCollectionError("invalid_equity_symbol")
        return value
    raise MarketDataCollectionError("unsupported_asset_class")


def _parse_timestamp(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, date):
        parsed = datetime.combine(raw, time.min, tzinfo=timezone.utc)
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        parsed = datetime.fromtimestamp(float(raw) / (1000.0 if float(raw) > 10_000_000_000 else 1.0), tz=timezone.utc)
    elif isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.combine(date.fromisoformat(raw), time.min, tzinfo=timezone.utc)
    else:
        raise ProviderCollectionError("invalid_timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ProviderCollectionError("invalid_numeric_value")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProviderCollectionError("invalid_numeric_value") from exc
    if not math.isfinite(number):
        raise ProviderCollectionError("invalid_numeric_value")
    if field == "volume":
        if number < 0:
            raise ProviderCollectionError("invalid_volume")
    elif number <= 0:
        raise ProviderCollectionError("invalid_price")
    return number


class UnifiedMarketDataCollector:
    """One ingestion facade; provider rows remain distinct and never update trading feeds."""

    def __init__(self, settings: Any, db_manager: Any, http: AsyncProviderHTTP | None = None):
        self.settings = settings
        self.db_manager = db_manager
        self._owns_http = http is None
        self._transport_client: httpx.AsyncClient | None = None
        if http is None:
            self._transport_client = httpx.AsyncClient(
                timeout=httpx.Timeout(12.0, connect=4.0),
                limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
                follow_redirects=False,
            )
            self.http = AsyncProviderHTTP(
                connect_timeout=4.0,
                read_timeout=12.0,
                max_connections=12,
                max_keepalive_connections=6,
                provider_concurrency=4,
                failure_threshold=3,
                cooldown_seconds=60,
                client=self._transport_client,
                max_retries=1,
                backoff_base_seconds=0.2,
                backoff_max_seconds=1.0,
                jitter_ratio=0.1,
            )
        else:
            self.http = http

    async def aclose(self) -> None:
        if self._owns_http:
            await self.http.aclose()
            if self._transport_client is not None:
                await self._transport_client.aclose()

    @staticmethod
    def catalog() -> dict[str, dict[str, Any]]:
        return {name: dict(info) for name, info in PROVIDER_CATALOG.items()}

    @staticmethod
    def _validate_base_url(url: str, allowed_host: str) -> str:
        parsed = urlsplit(str(url))
        try:
            port = parsed.port
        except ValueError as exc:
            raise ProviderCollectionError("provider_endpoint_not_allowlisted") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != allowed_host
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderCollectionError("provider_endpoint_not_allowlisted")
        return str(url).rstrip("/")

    @staticmethod
    def _request_symbols(asset_class: str, symbol: str) -> dict[str, str]:
        if asset_class == "crypto":
            base, quote = symbol.split("/", 1)
            return {"base": base, "quote": quote, "binance": f"{base}{quote}"}
        if asset_class == "forex":
            base, quote = symbol.split("/", 1)
            return {"base": base, "quote": quote}
        return {"equity": symbol}

    async def collect(
        self,
        *,
        asset_class: str,
        symbols: list[str],
        providers: list[str],
        timeframe: str = "1d",
        limit: int = 100,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if not bool(getattr(self.settings, "MARKET_DATA_INGESTION_ENABLED", False)):
            raise ProviderCollectionError("ingestion_disabled")
        asset_class = str(asset_class).strip().lower()
        if asset_class not in ASSET_CLASSES:
            raise MarketDataCollectionError("unsupported_asset_class")
        timeframe = str(timeframe).strip().lower()
        if timeframe not in TIMEFRAMES:
            raise MarketDataCollectionError("unsupported_timeframe")
        if not 1 <= int(limit) <= 1000:
            raise MarketDataCollectionError("limit_out_of_range")
        if not symbols or len(symbols) > 10:
            raise MarketDataCollectionError("symbol_count_out_of_range")
        if not providers or len(providers) > 3 or len(set(providers)) != len(providers):
            raise MarketDataCollectionError("provider_count_out_of_range")
        unknown = set(providers) - KNOWN_PROVIDERS
        if unknown:
            raise MarketDataCollectionError("unknown_provider")
        normalized = [canonical_symbol(asset_class, symbol) for symbol in symbols]
        if len(set(normalized)) != len(normalized):
            raise MarketDataCollectionError("duplicate_symbols")

        work: list[tuple[str, str]] = [(provider, symbol) for provider in providers for symbol in normalized]
        semaphore_by_provider = {
            provider: asyncio.Semaphore(1 if provider == "alpha_vantage" else 4)
            for provider in providers
        }

        async def collect_one(provider: str, symbol: str) -> dict[str, Any]:
            async with semaphore_by_provider[provider]:
                return await self._collect_one(provider, asset_class, symbol, timeframe, int(limit), bool(dry_run))

        results = await asyncio.gather(
            *(collect_one(provider, symbol) for provider, symbol in work),
            return_exceptions=True,
        )
        provider_results: list[dict[str, Any]] = []
        for (provider, symbol), result in zip(work, results):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                code = result.code if isinstance(result, ProviderCollectionError) else (
                    str(result) if isinstance(result, MarketDataCollectionError) else "upstream_unavailable"
                )
                provider_results.append({
                    "provider": provider,
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "status": "blocked" if code in {
                        "provider_disabled",
                        "source_not_approved_for_automated_ingestion",
                        "missing_credentials",
                        "dataset_semantics_not_ohlcv",
                    } else "error",
                    "rows_received": 0,
                    "persisted_rows": 0,
                    "error_code": code,
                })
            else:
                provider_results.append(result)

        successful = sum(result["status"] in {"preview", "persisted"} for result in provider_results)
        failures = len(provider_results) - successful
        return {
            "status": "completed" if failures == 0 else ("partial" if successful else "attention"),
            "mode": "dry_run" if dry_run else "persisted",
            "asset_class": asset_class,
            "requested_symbols": normalized,
            "requested_providers": list(providers),
            "provider_catalog": self.catalog(),
            "timeframe": timeframe,
            "requested_limit": int(limit),
            "provider_results": provider_results,
            "orders_sent": 0,
            "trading_feed_updated": False,
            "model_weights_changed": False,
        }

    async def _collect_one(
        self,
        provider: str,
        asset_class: str,
        symbol: str,
        timeframe: str,
        limit: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        enabled_key = {
            "binance_public": "MARKET_DATA_BINANCE_PUBLIC_ENABLED",
            "alpha_vantage": "MARKET_DATA_ALPHA_VANTAGE_ENABLED",
        }.get(provider)
        if provider == "yahoo_chart":
            raise ProviderCollectionError("source_not_approved_for_automated_ingestion")
        if provider == "coingecko":
            raise ProviderCollectionError("dataset_semantics_not_ohlcv")
        if enabled_key and not bool(getattr(self.settings, enabled_key, False)):
            raise ProviderCollectionError("provider_disabled")
        if provider == "alpha_vantage" and not getattr(self.settings, "ALPHA_VANTAGE_API_KEY", None):
            raise ProviderCollectionError("missing_credentials")
        if provider == "binance_public" and asset_class != "crypto":
            raise ProviderCollectionError("unsupported_asset_class")
        if provider == "alpha_vantage" and asset_class == "crypto":
            raise ProviderCollectionError("unsupported_asset_class")
        if provider == "alpha_vantage" and timeframe != "1d":
            raise ProviderCollectionError("unsupported_timeframe")

        if provider == "binance_public":
            candles = await self._fetch_binance(symbol, timeframe, limit)
        else:
            candles = await self._fetch_alpha_vantage(asset_class, symbol, limit)
        candles = self._validate_and_limit(candles, symbol, asset_class, timeframe, limit)
        if not candles:
            raise ProviderCollectionError("no_closed_candles")
        for candle in candles:
            candle["source"] = provider

        persisted = 0
        if not dry_run:
            upsert = getattr(self.db_manager, "upsert_market_candles", None)
            if not callable(upsert):
                raise ProviderCollectionError("persistence_unavailable")
            persisted = await asyncio.to_thread(upsert, candles)
        return {
            "provider": provider,
            "asset_class": asset_class,
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "preview" if dry_run else "persisted",
            "rows_received": len(candles),
            "persisted_rows": persisted,
            "first_timestamp": candles[0]["timestamp"].isoformat(),
            "last_timestamp": candles[-1]["timestamp"].isoformat(),
            "volume_unavailable_rows": sum(row["volume_status"] == "unavailable_zero" for row in candles),
            "error_code": None,
        }

    async def _fetch_binance(self, symbol: str, timeframe: str, limit: int) -> list[dict[str, Any]]:
        if timeframe not in {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}:
            raise ProviderCollectionError("unsupported_timeframe")
        base_url = self._validate_base_url(
            getattr(self.settings, "BINANCE_PUBLIC_BASE_URL", "https://data-api.binance.vision"),
            "data-api.binance.vision",
        )
        pair = symbol.replace("/", "")
        payload = await self.http.get_json(
            "binance_public_market_data",
            f"{base_url}/api/v3/klines",
            params={"symbol": pair, "interval": timeframe, "limit": min(limit, 1000)},
        )
        if not isinstance(payload, list):
            raise ProviderCollectionError("malformed_provider_response")
        rows = []
        now = datetime.now(timezone.utc)
        for item in payload:
            if not isinstance(item, (list, tuple)) or len(item) < 7:
                raise ProviderCollectionError("malformed_provider_response")
            close_time = _parse_timestamp(item[6])
            if close_time > now:
                continue
            rows.append({
                "timestamp": _parse_timestamp(item[0]),
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "volume": item[5],
                "volume_status": "reported",
            })
        return rows

    async def _fetch_alpha_vantage(self, asset_class: str, symbol: str, limit: int) -> list[dict[str, Any]]:
        api_key = getattr(self.settings, "ALPHA_VANTAGE_API_KEY", None)
        if not api_key:
            raise ProviderCollectionError("missing_credentials")
        pair = self._request_symbols(asset_class, symbol)
        params: dict[str, Any] = {"apikey": api_key, "outputsize": "compact", "datatype": "json"}
        if asset_class == "equity":
            params.update({"function": "TIME_SERIES_DAILY", "symbol": pair["equity"]})
            volume_required = True
        elif asset_class == "forex":
            params.update({"function": "FX_DAILY", "from_symbol": pair["base"], "to_symbol": pair["quote"]})
            volume_required = False
        else:
            raise ProviderCollectionError("unsupported_asset_class")

        payload = await self.http.get_json(
            "alpha_vantage_market_data",
            "https://www.alphavantage.co/query",
            params=params,
        )
        if not isinstance(payload, dict):
            raise ProviderCollectionError("malformed_provider_response")
        series_key = next((key for key, value in payload.items() if "time series" in key.lower() and isinstance(value, dict)), None)
        if not series_key:
            if any(key in payload for key in ("Note", "Information", "Error Message")):
                # Do not return provider text; it can contain request details or account-specific information.
                raise ProviderCollectionError("provider_rate_limit_plan_or_symbol_error")
            raise ProviderCollectionError("malformed_provider_response")

        rows = []
        for day, values in payload[series_key].items():
            if not isinstance(values, dict):
                raise ProviderCollectionError("malformed_provider_response")
            normalized = {str(key).lower(): value for key, value in values.items()}

            def field(prefix: str) -> Any:
                return next((value for key, value in normalized.items() if key.startswith(prefix)), None)

            raw_volume = field("5. volume") if volume_required else None
            volume_status = "reported" if raw_volume is not None else "unavailable_zero"
            if raw_volume is None and volume_required:
                raise ProviderCollectionError("volume_missing_for_equity")
            rows.append({
                "timestamp": _parse_timestamp(day),
                "open": field("1. open"),
                "high": field("2. high"),
                "low": field("3. low"),
                "close": field("4. close"),
                "volume": raw_volume if raw_volume is not None else 0.0,
                "volume_status": volume_status,
            })
        return rows

    @staticmethod
    def _validate_and_limit(
        raw_rows: list[dict[str, Any]],
        symbol: str,
        asset_class: str,
        timeframe: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        interval = TIMEFRAMES[timeframe]
        unique: dict[datetime, dict[str, Any]] = {}
        for raw in raw_rows:
            timestamp = _parse_timestamp(raw.get("timestamp"))
            if timestamp > now:
                raise ProviderCollectionError("future_candle_rejected")
            # Providers without an explicit close timestamp use a conservative full-interval cutoff.
            if timestamp + timedelta(seconds=interval) > now:
                continue
            row = {
                "source": "",
                "asset_class": asset_class,
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": timestamp,
                "open": _finite_number(raw.get("open"), "price"),
                "high": _finite_number(raw.get("high"), "price"),
                "low": _finite_number(raw.get("low"), "price"),
                "close": _finite_number(raw.get("close"), "price"),
                "volume": _finite_number(raw.get("volume", 0.0), "volume"),
                "volume_status": str(raw.get("volume_status", "reported")),
            }
            if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]) or row["low"] > row["high"]:
                raise ProviderCollectionError("inconsistent_ohlc_bounds")
            if row["volume_status"] not in {"reported", "unavailable_zero"}:
                raise ProviderCollectionError("invalid_volume_status")
            unique[timestamp] = row
        return [unique[timestamp] for timestamp in sorted(unique)][-limit:]
