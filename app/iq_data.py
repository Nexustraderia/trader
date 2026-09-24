"""Read-only IQ Option Practice candle adapter.

This module intentionally exposes only historical/stream candle reads. It never
imports or calls order methods from the community client.
"""
import os
import socket
import threading
import time
import asyncio
import concurrent.futures

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
# The IQ Option handshake and initial balance synchronization can take longer
# than a normal HTTP request. A short global socket timeout causes false
# failures before the WebSocket session is ready.
socket.setdefaulttimeout(30)

_aio_loop = None
_aio_thread = None
_aio_client = None
_aio_last_error = None


def _async_call(coro, timeout: float = 45):
    """Run one read-only IQ request on the persistent asyncio WebSocket."""
    global _aio_loop, _aio_thread, _aio_client
    if _aio_loop is None:
        _aio_loop = asyncio.new_event_loop()
        _aio_thread = threading.Thread(target=_aio_loop.run_forever, daemon=True, name="iq-aio-loop")
        _aio_thread.start()
    future = asyncio.run_coroutine_threadsafe(coro, _aio_loop)
    global _aio_last_error
    try:
        return future.result(timeout=timeout)
    except Exception as error:
        _aio_last_error = f"{type(error).__name__}: {str(error)[:180]}"
        future.cancel()
        raise


async def _async_client_connect():
    return True


def _get_async_client():
    global _aio_client
    if _aio_client is None:
        _aio_client = _async_call(_async_client_connect())
    return _aio_client


def _async_candles(active: str, size: int, count: int) -> list[dict]:
    try:
        from .iq_ws import get_candles
    except ImportError:
        from iq_ws import get_candles
    active_id = _opcode_for_asset(active)
    if active_id is None:
        raise ValueError(f"IQ Option active opcode unavailable: {active}")
    return _async_call(get_candles(
        os.environ["IQ_OPTION_EMAIL"].strip(),
        os.environ["IQ_OPTION_PASSWORD"],
        active_id,
        size,
        count,
    ), timeout=60)


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
                if isinstance(connected, tuple):
                    status, reason = (connected + (None, None))[:2]
                else:
                    status, reason = connected, None
                if status is not True:
                    result.append(RuntimeError(f"IQ Option connect rejected: {str(reason)[:120]}"))
                    return
                client.change_balance("PRACTICE")
                result.append(True)
            except Exception as error:
                result.append(error)
            finally:
                done.set()

        threading.Thread(target=connect_worker, daemon=True, name="iq-connect").start()
        if not done.wait(45):
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
    """Return IQ assets confirmed by successful IQ-only candle responses."""
    global _asset_cache, _asset_cache_at, _asset_modes_cache
    now = time.time()
    if _asset_cache and now - _asset_cache_at < 300:
        return set(_asset_cache)
    candidates = list(IQ_SYMBOLS.values()) + [f"{base}-OTC" for base in OTC_BASES]
    candidates = sorted(set(candidates))

    async def probe_all():
        try:
            from .iq_ws import get_candles
        except ImportError:
            from iq_ws import get_candles
        email = os.environ["IQ_OPTION_EMAIL"].strip()
        password = os.environ["IQ_OPTION_PASSWORD"]
        results = await asyncio.gather(
            *(get_candles(email, password, _opcode_for_asset(active), 60, 2) for active in candidates),
            return_exceptions=True,
        )
        opened = [(active, result) for active, result in zip(candidates, results) if isinstance(result, list) and result]
        failures = [result for result in results if isinstance(result, Exception)]
        return opened, failures

    try:
        opened, failures = _async_call(probe_all(), timeout=180)
    except Exception as error:
        detail = _aio_last_error or f"{type(error).__name__}: {str(error)[:180]}"
        raise RuntimeError(f"IQ Option candle connection unavailable ({detail})") from None
    if not opened:
        detail = f"; first={type(failures[0]).__name__}: {str(failures[0])[:160]}" if failures else ""
        raise RuntimeError(f"IQ Option returned no candle assets{detail}")
    assets = {_compact_asset(active) for active, _ in opened}
    modes = {asset: {"candles"} for asset in assets}
    if not assets:
        raise RuntimeError("IQ Option returned no candle assets")
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
    if normalized.endswith("-OTC"):
        return bool(_asset_cache) and normalized in {_display_symbol(asset) for asset in _asset_cache}
    # Normal IQ symbols have stable numeric opcodes and can be tested directly
    # even while the optional OTC/open-catalog refresh is still in progress.
    return normalized in IQ_SYMBOLS


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
    opcode = _opcode_for_asset(active)
    if opcode is None:
        raise ValueError(f"IQ Option active opcode unavailable: {normalized}")
    candles = _async_candles(active, size, min(count, 1000))
    if not candles:
        raise TimeoutError(f"IQ Option candles unavailable: {normalized}/{interval}")
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
