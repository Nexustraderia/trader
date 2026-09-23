import calendar
import os
import time

import requests

SYMBOLS = {
    "EUR/JPY": "EURJPY=X",
    "EUR/USD": "EURUSD=X",
    "USD/JPY": "JPY=X",
    "GBP/USD": "GBPUSD=X",
    "GBP/JPY": "GBPJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "CAD=X",
    "XAU/USD": "GC=F",
}

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
_LAST_SOURCE = "Yahoo Finance Chart API (fallback)"
_LAST_ERROR = None


def normalize_symbol(value: str) -> str:
    raw = value.strip().upper().replace("-", "/")
    aliases = {"EURJPY": "EUR/JPY", "EURUSD": "EUR/USD", "USDJPY": "USD/JPY", "GBPUSD": "GBP/USD", "GBPJPY": "GBP/JPY", "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "XAUUSD": "XAU/USD", "OURO": "XAU/USD"}
    return aliases.get(raw, raw)


def _fetch_twelve_data(symbol: str, interval: str, count: int) -> list[dict]:
    api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    if not api_key:
        return []
    response = requests.get(
        TWELVE_DATA_URL,
        params={"symbol": normalize_symbol(symbol), "interval": interval.replace("m", "min").replace("h", "h"), "outputsize": min(count, 5000), "timezone": "UTC", "apikey": api_key},
        headers={"User-Agent": "NEXUS-IA-TRADER/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "error" or not payload.get("values"):
        raise RuntimeError(payload.get("message", "Twelve Data sem candles"))
    candles = []
    for item in reversed(payload["values"]):
        timestamp = item.get("datetime")
        try:
            epoch = calendar.timegm(time.strptime(timestamp, "%Y-%m-%d %H:%M:%S"))
        except (TypeError, ValueError):
            epoch = None
        candles.append({"timestamp": epoch, "open": float(item["open"]), "high": float(item["high"]), "low": float(item["low"]), "close": float(item["close"]), "volume": float(item.get("volume") or 0)})
    return candles[-count:]


def market_data_source() -> str:
    return _LAST_SOURCE


def market_data_diagnostics() -> dict:
    """Return provider state without exposing API keys or response bodies."""
    return {
        "source": _LAST_SOURCE,
        "last_error": _LAST_ERROR,
        "twelve_data_configured": bool(os.getenv("TWELVEDATA_API_KEY", "").strip()),
    }


def fetch_candles(symbol: str, interval: str = "5m", range_: str = "1d", count: int = 80) -> list[dict]:
    global _LAST_SOURCE, _LAST_ERROR
    _LAST_ERROR = None
    normalized = normalize_symbol(symbol)
    if os.getenv("TWELVEDATA_API_KEY", "").strip():
        try:
            candles = _fetch_twelve_data(normalized, interval, count)
            if candles:
                _LAST_SOURCE = "Twelve Data"
                return candles
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as error:
            _LAST_ERROR = f"Twelve Data: {type(error).__name__}"
    ticker = SYMBOLS.get(normalized)
    if not ticker:
        raise ValueError(f"Ativo não suportado: {symbol}")

    last_error = None
    payload = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            url = f"https://{host}/v8/finance/chart/{ticker}"
            response = requests.get(
                url,
                params={"interval": interval, "range": range_, "includePrePost": "false"},
                headers={"User-Agent": "Mozilla/5.0 (NEXUS-IA-TRADER prototype)"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json().get("chart", {}).get("result", [None])[0]
            if payload:
                break
        except (requests.RequestException, ValueError, KeyError) as error:
            last_error = error
            _LAST_ERROR = f"Yahoo Finance: {type(error).__name__}"
    if not payload:
        raise RuntimeError(f"Fonte de candles indisponível: {type(last_error).__name__}")
    _LAST_SOURCE = "Yahoo Finance Chart API (fallback)"
    timestamps = payload.get("timestamp") or []
    quote = payload["indicators"]["quote"][0]
    candles = []
    for index, timestamp in enumerate(timestamps):
        values = {key: quote.get(key, [None] * len(timestamps))[index] for key in ("open", "high", "low", "close", "volume")}
        if values["close"] is not None:
            candles.append({"timestamp": timestamp, **values})
    return candles[-count:]


def is_fresh(candles: list[dict], max_age_seconds: int) -> bool:
    if not candles or candles[-1].get("timestamp") is None:
        return False
    return time.time() - float(candles[-1]["timestamp"]) <= max_age_seconds
