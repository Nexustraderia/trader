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
OTC_BASES = ("EURUSD", "EURJPY", "USDJPY", "GBPUSD", "GBPJPY", "AUDUSD", "USDCAD")

_client = None
_client_lock = threading.Lock()
_asset_cache = set()
_asset_cache_at = 0.0
_asset_modes_cache = {}


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
    global _asset_cache, _asset_cache_at, _asset_modes_cache
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
    modes = {}
    # These are the IQ Option binary-style modalities. They share the same
    # candle feed, so an asset open in both binary and digital is scanned once.
    supported_categories = {"binary", "turbo", "digital"}
    for category_name, category in open_time.items():
        if str(category_name).lower() not in supported_categories:
            continue
        if isinstance(category, dict):
            for name, status in category.items():
                if isinstance(status, dict) and status.get("open"):
                    asset = str(name).upper()
                    assets.add(asset)
                    modes.setdefault(asset, set()).add(str(category_name).lower())
    _asset_cache = assets
    _asset_modes_cache = modes
    _asset_cache_at = now
    return set(assets)


def _display_symbol(asset: str) -> str:
    """Convert IQ's compact catalog code to the public scanner symbol."""
    raw = asset.strip().upper().replace("_", "-").replace(" ", "-")
    if raw.endswith("-OTC"):
        base = raw[:-4]
        return f"{base[:3]}/{base[3:]}-OTC" if len(base) == 6 else raw
    known = {value: key for key, value in IQ_SYMBOLS.items()}
    if raw in known:
        return known[raw]
    return f"{raw[:3]}/{raw[3:]}" if len(raw) == 6 and raw.isalpha() else raw


def available_signal_assets() -> list[str]:
    """Return unique open binary/turbo/digital assets for automatic scanning."""
    assets = available_iq_assets()
    return sorted({_display_symbol(asset) for asset in assets})


def available_asset_modes() -> dict[str, list[str]]:
    """Return the open IQ modalities for each display symbol."""
    if not _asset_cache:
        available_iq_assets()
    result = {}
    for asset, modes in _asset_modes_cache.items():
        result[_display_symbol(asset)] = sorted(modes)
    return result


def is_iq_asset_open(symbol: str) -> bool:
    """Check availability before generating a signal for any asset."""
    normalized = symbol.strip().upper()
    active = normalized.replace("/", "")
    if normalized.endswith("-OTC"):
        active = active[:-4] + "-OTC"
    if not active:
        return False
    try:
        assets = available_iq_assets()
    except RuntimeError:
        return True
    candidates = {active.upper(), active.upper().replace("-OTC", "_OTC"), active.upper().replace("-OTC", " OTC")}
    if candidates.intersection(assets):
        return True
    return False


def fetch_iq_candles(symbol: str, interval: str, count: int) -> list[dict]:
    active = IQ_SYMBOLS.get(symbol)
    if not active:
        active = symbol.replace("/", "")
    size = INTERVAL_SECONDS.get(interval)
    if not active or not size:
        raise ValueError(f"IQ Option symbol/interval unsupported: {symbol}/{interval}")
    if symbol.endswith("-OTC"):
        assets = available_iq_assets()
        candidates = {active.upper(), active.upper().replace("-OTC", "_OTC"), active.upper().replace("-OTC", " OTC")}
        if not candidates.intersection(assets):
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


def otc_open_assets() -> list[str]:
    """Return configured OTC codes that the cached IQ catalog marks open."""
    assets = available_iq_assets()
    opened = []
    for base in OTC_BASES:
        candidates = {f"{base}-OTC", f"{base}_OTC", f"{base} OTC"}
        if candidates.intersection(assets):
            opened.append(f"{base}-OTC")
    return opened


def cached_otc_open_assets() -> list[str]:
    """Return the last catalog snapshot without making a network call."""
    if not _asset_cache:
        return []
    opened = []
    for base in OTC_BASES:
        candidates = {f"{base}-OTC", f"{base}_OTC", f"{base} OTC"}
        if candidates.intersection(_asset_cache):
            opened.append(f"{base}-OTC")
    return opened
