import time

try:
    from .iq_data import fetch_iq_candles, iq_option_configured, is_iq_asset_open
except ImportError:
    from iq_data import fetch_iq_candles, iq_option_configured, is_iq_asset_open

_LAST_SOURCE = "IQ Option Practice candles (read-only)"
_LAST_ERROR = None


def normalize_symbol(value: str) -> str:
    raw = value.strip().upper()
    if raw.endswith("-OTC"):
        base = raw[:-4].replace("/", "")
        otc_aliases = {
            "EURJPY": "EUR/JPY", "EURUSD": "EUR/USD", "USDJPY": "USD/JPY",
            "GBPUSD": "GBP/USD", "GBPJPY": "GBP/JPY", "AUDUSD": "AUD/USD",
            "USDCAD": "USD/CAD",
        }
        return f"{otc_aliases[base]}-OTC" if base in otc_aliases else raw
    raw = raw.replace("-", "/")
    aliases = {
        "EURJPY": "EUR/JPY", "EURUSD": "EUR/USD", "USDJPY": "USD/JPY",
        "GBPUSD": "GBP/USD", "GBPJPY": "GBP/JPY", "AUDUSD": "AUD/USD",
        "USDCAD": "USD/CAD", "XAUUSD": "XAU/USD", "OURO": "XAU/USD",
    }
    return aliases.get(raw, raw)


def market_data_source() -> str:
    return _LAST_SOURCE


def market_data_diagnostics() -> dict:
    return {
        "source": _LAST_SOURCE,
        "last_error": _LAST_ERROR,
        "provider": "IQ Option only",
        "iq_option_configured": iq_option_configured(),
    }


def fetch_candles(symbol: str, interval: str = "5m", range_: str = "1d", count: int = 80) -> list[dict]:
    del range_  # IQ Option candles are requested by interval and count.
    global _LAST_ERROR
    _LAST_ERROR = None
    normalized = normalize_symbol(symbol)
    if not iq_option_configured():
        _LAST_ERROR = "IQ Option credentials not configured"
        raise RuntimeError(_LAST_ERROR)
    if not is_iq_asset_open(normalized):
        _LAST_ERROR = f"IQ Option asset not confirmed open: {normalized}"
        raise RuntimeError(_LAST_ERROR)
    try:
        candles = fetch_iq_candles(normalized, interval, count)
    except Exception as error:
        _LAST_ERROR = f"IQ Option: {type(error).__name__}"
        raise
    if not candles:
        _LAST_ERROR = "IQ Option returned no candles"
        raise RuntimeError(_LAST_ERROR)
    return candles


def is_fresh(candles: list[dict], max_age_seconds: int) -> bool:
    if not candles or candles[-1].get("timestamp") is None:
        return False
    return time.time() - float(candles[-1]["timestamp"]) <= max_age_seconds
