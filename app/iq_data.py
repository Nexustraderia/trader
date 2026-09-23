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


def fetch_iq_candles(symbol: str, interval: str, count: int) -> list[dict]:
    active = IQ_SYMBOLS.get(symbol)
    size = INTERVAL_SECONDS.get(interval)
    if not active or not size:
        raise ValueError(f"IQ Option symbol/interval unsupported: {symbol}/{interval}")
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
