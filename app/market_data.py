import time

import requests

SYMBOLS = {
    "EUR/JPY": "EURJPY=X",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "XAU/USD": "GC=F",
}


def normalize_symbol(value: str) -> str:
    raw = value.strip().upper().replace("-", "/")
    aliases = {"EURJPY": "EUR/JPY", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "XAUUSD": "XAU/USD", "OURO": "XAU/USD"}
    return aliases.get(raw, raw)


def fetch_candles(symbol: str, interval: str = "5m", range_: str = "1d", count: int = 80) -> list[dict]:
    normalized = normalize_symbol(symbol)
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
    if not payload:
        raise RuntimeError(f"Fonte de candles indisponível: {type(last_error).__name__}")
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
