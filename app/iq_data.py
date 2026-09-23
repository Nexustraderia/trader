"""Read-only IQ Option Practice candle adapter.

This module intentionally exposes only historical/stream candle reads. It never
imports or calls order methods from the community client.
"""
import os
import threading
import time


IQ_SYMBOLS = {
    "EUR/JPY": "EURJPY",
    "EUR/USD": "EURUSD",
    "USD/JPY": "USDJPY",
    "GBP/USD": "GBPUSD",
    "GBP/JPY": "GBPJPY",
    "AUD/USD": "AUDUSD",
    "USD/CAD": "USDCAD",
    "XAU/USD": "XAUUSD",
}
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}

_client = None
_client_lock = threading.Lock()
_asset_cache = set()
_asset_cache_at = 0.0


def iq_option_configured() -> bool:
    return bool(os.getenv("IQ_OPTION_EMAIL", "").strip() and os.getenv("IQ_OPTION_PASSWORD", "").strip())


def _get_client():
    global _client
    if not iq_option_configured():
        raise RuntimeError("IQ Option Practice credentials not configured")
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError as error:
            raise RuntimeError("iqoptionapi dependency unavailable") from error
        client = IQ_Option(os.environ["IQ_OPTION_EMAIL"].strip(), os.environ["IQ_OPTION_PASSWORD"])
        connected = client.connect()
        if connected is False:
            raise RuntimeError("IQ Option connection failed")
        client.change_balance("PRACTICE")
        _client = client
        return client


def available_iq_assets() -> set[str]:
    """Return currently open IQ Option asset codes, cached briefly."""
    global _asset_cache, _asset_cache_at
    now = time.time()
    if _asset_cache and now - _asset_cache_at < 300:
        return set(_asset_cache)
    try:
        open_time = _get_client().get_all_open_time(0)
    except Exception:
        raise RuntimeError("IQ Option OTC catalog unavailable") from None
    if not isinstance(open_time, dict):
        raise RuntimeError("IQ Option asset catalog unavailable")
    assets = set()
    for category in open_time.values():
        if isinstance(category, dict):
            for name, status in category.items():
                if isinstance(status, dict) and status.get("open"):
                    assets.add(str(name).upper())
    _asset_cache = assets
    _asset_cache_at = now
    return set(assets)


def is_iq_asset_open(symbol: str) -> bool:
    """Check availability before generating a signal for any asset."""
    normalized = symbol.strip().upper()
    active = IQ_SYMBOLS.get(normalized)
    if not active and normalized.endswith("-OTC"):
        active = normalized[:-4].replace("/", "") + "-OTC"
    if not active:
        return False
    try:
        assets = available_iq_assets()
    except RuntimeError:
        # For normal Forex, build_analysis performs the authoritative fresh
        # candle check. OTC remains strict because its session is platform-only.
        return not normalized.endswith("-OTC")
    if active.upper() in assets:
        return True
    # A normal pair is considered eligible for the subsequent fresh-candle
    # gate; this avoids false closures when IQ's heavy catalog is incomplete.
    return not normalized.endswith("-OTC")


def fetch_iq_candles(symbol: str, interval: str, count: int) -> list[dict]:
    active = IQ_SYMBOLS.get(symbol)
    if not active and symbol.endswith("-OTC"):
        active = symbol.replace("/", "")
    size = INTERVAL_SECONDS.get(interval)
    if not active or not size:
        raise ValueError(f"IQ Option symbol/interval unsupported: {symbol}/{interval}")
    if symbol.endswith("-OTC") and active.upper() not in available_iq_assets():
        raise RuntimeError(f"IQ Option asset not open: {active}")
    candles = _get_client().get_candles(active, size, min(count, 1000), int(time.time()))
    if not candles:
        raise RuntimeError("IQ Option returned no candles")
    normalized = []
    for candle in sorted(candles, key=lambda item: float(item.get("from", item.get("at", 0)))):
        timestamp = candle.get("from", candle.get("at"))
        normalized.append({
            "timestamp": int(float(timestamp)),
            "open": float(candle["open"]),
            "high": float(candle["max"] if "max" in candle else candle["high"]),
            "low": float(candle["min"] if "min" in candle else candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle.get("volume", 0) or 0),
        })
    return normalized[-count:]
