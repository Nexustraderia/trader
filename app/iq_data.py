"""Read-only IQ Option Practice candle adapter.

This module intentionally exposes only historical/stream candle reads. It never
imports or calls order methods from the community client.
"""
import os
import socket
import threading
import time

import iqoptionapi.constants as OP_code


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
_connect_blocked_until = 0.0
_last_connect_error = None
socket.setdefaulttimeout(10)


def iq_option_configured() -> bool:
    return bool(os.getenv("IQ_OPTION_EMAIL", "").strip() and os.getenv("IQ_OPTION_PASSWORD", "").strip())


def _get_client():
    global _client, _connect_blocked_until, _last_connect_error
    if not iq_option_configured():
        raise RuntimeError("IQ Option Practice credentials not configured")
    with _client_lock:
        if _client is not None:
            return _client
        now = time.time()
        if now < _connect_blocked_until:
            detail = _last_connect_error or "IQ Option connection temporarily unavailable"
            raise TimeoutError(detail)
        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError as error:
            raise RuntimeError("iqoptionapi dependency unavailable") from error
        client = IQ_Option(os.environ["IQ_OPTION_EMAIL"].strip(), os.environ["IQ_OPTION_PASSWORD"])
        result = []
        done = threading.Event()

        def connect_worker():
            try:
                connected = client.connect()
                if connected is False:
                    result.append(False)
                else:
                    client.change_balance("PRACTICE")
                    result.append(True)
            except Exception as error:
                result.append(error)
            finally:
                done.set()

        threading.Thread(target=connect_worker, daemon=True, name="iq-connect").start()
        if not done.wait(15):
            _last_connect_error = "IQ Option connection timeout"
            _connect_blocked_until = time.time() + 60
            raise TimeoutError("IQ Option connection timeout")
        connected = result[0] if result else False
        if isinstance(connected, Exception):
            _last_connect_error = f"IQ Option connection failed: {type(connected).__name__}"
            _connect_blocked_until = time.time() + 60
            raise connected
        if connected is False:
            _last_connect_error = "IQ Option connection failed"
            _connect_blocked_until = time.time() + 60
            raise RuntimeError("IQ Option connection failed")
        _last_connect_error = None
        _connect_blocked_until = 0.0
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


def _compact_asset(asset: str) -> str:
    """Normalize IQ names such as EUR/USD (OTC) to EURUSD-OTC."""
    raw = str(asset or "").strip().upper()
    raw = raw.replace("(", "").replace(")", "")
    raw = raw.replace("/", "").replace("_", "-").replace(" ", "-")
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw


def _display_symbol(asset: str) -> str:
    """Convert IQ catalog names to the public scanner symbol."""
    raw = _compact_asset(asset)
    if raw.endswith("-OTC"):
        base = raw[:-4]
        return f"{base[:3]}/{base[3:]}-OTC" if len(base) == 6 else raw
    known = {value: key for key, value in IQ_SYMBOLS.items()}
    if raw in known:
        return known[raw]
    return f"{raw[:3]}/{raw[3:]}" if len(raw) == 6 and raw.isalpha() else raw


def _opcode_for_asset(asset: str):
    """Resolve an opcode regardless of the catalog's OTC spelling."""
    return OP_code.ACTIVES.get(str(asset).strip().upper()) or OP_code.ACTIVES.get(_compact_asset(asset))


def available_signal_assets() -> list[str]:
    """Return unique open binary/turbo/digital assets for automatic scanning."""
    assets = available_iq_assets()
    # The community client can only request candles for assets present in its
    # ACTIVES opcode map. Ignore catalog entries that this pinned client cannot
    # address instead of allowing one exotic entry to break a scan cycle.
    return sorted({_display_symbol(asset) for asset in assets if _opcode_for_asset(asset) is not None})


def cached_signal_assets() -> list[str]:
    """Return discovered assets without contacting IQ Option."""
    return sorted({_display_symbol(asset) for asset in _asset_cache})


def available_asset_modes() -> dict[str, list[str]]:
    """Return the open IQ modalities for each display symbol."""
    result = {}
    for asset, modes in _asset_modes_cache.items():
        result[_display_symbol(asset)] = sorted(modes)
    return result


def is_iq_asset_open(symbol: str) -> bool:
    """Check availability before generating a signal for any asset."""
    normalized = _display_symbol(symbol)
    # Every asset, including normal forex pairs, must be confirmed open by the
    # Every asset must be confirmed open by the IQ catalog before analysis.
    return bool(_asset_cache) and normalized in {_display_symbol(asset) for asset in _asset_cache}


def fetch_iq_candles(symbol: str, interval: str, count: int) -> list[dict]:
    normalized = _display_symbol(symbol)
    active = IQ_SYMBOLS.get(normalized)
    if not active:
        active = _compact_asset(normalized)
    size = INTERVAL_SECONDS.get(interval)
    if not active or not size:
        raise ValueError(f"IQ Option symbol/interval unsupported: {symbol}/{interval}")
    if normalized.endswith("-OTC"):
        assets = available_iq_assets()
        if normalized not in {_display_symbol(asset) for asset in assets}:
            raise RuntimeError(f"IQ Option asset not open: {active}")
    client = _get_client()
    client.api.candles.candles_data = None
    opcode = _opcode_for_asset(active)
    if opcode is None:
        raise ValueError(f"IQ Option active opcode unavailable: {normalized}")
    client.api.getcandles(opcode, size, min(count, 1000), int(time.time()))
    deadline = time.time() + 12
    while client.check_connect and client.api.candles.candles_data is None and time.time() < deadline:
        time.sleep(0.05)
    candles = client.api.candles.candles_data
    if candles is None:
        raise TimeoutError(f"IQ Option candles timeout: {symbol}/{interval}")
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
        target = _display_symbol(f"{base}-OTC")
        if target in {_display_symbol(asset) for asset in assets}:
            opened.append(target)
    return opened


def cached_otc_open_assets() -> list[str]:
    """Return the last catalog snapshot without making a network call."""
    if not _asset_cache:
        return []
    opened = []
    normalized_assets = {_display_symbol(asset) for asset in _asset_cache}
    for base in OTC_BASES:
        if _display_symbol(f"{base}-OTC") in normalized_assets:
            opened.append(_display_symbol(f"{base}-OTC"))
    return opened
