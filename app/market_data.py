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

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    response = requests.get(
        url,
        params={"interval": interval, "range": range_, "includePrePost": "false"},
        headers={"User-Agent": "NEXUS-IA-TRADER/0.1"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()["chart"]["result"][0]
    timestamps = payload.get("timestamp") or []
    quote = payload["indicators"]["quote"][0]
    candles = []
    for index, timestamp in enumerate(timestamps):
        values = {key: quote.get(key, [None] * len(timestamps))[index] for key in ("open", "high", "low", "close", "volume")}
        if values["close"] is not None:
            candles.append({"timestamp": timestamp, **values})
    return candles[-count:]
