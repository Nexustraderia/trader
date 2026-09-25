import os
from datetime import datetime, timedelta, timezone

import requests

from app.iq_data import available_signal_assets, fetch_iq_candles
from app.signal_engine import analyze_with_confirmation

CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@NexusTraderIA").strip()
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
EMAIL = os.environ["IQ_OPTION_EMAIL"].strip()
PASSWORD = os.environ["IQ_OPTION_PASSWORD"]
MIN_CONFIDENCE = int(os.getenv("AUTO_SIGNAL_MIN_CONFIDENCE", "80"))
MAX_ASSETS = int(os.getenv("MAX_SCAN_ASSETS", "12"))


def fresh(candles: list[dict], seconds: int) -> bool:
    return bool(candles) and datetime.now(timezone.utc).timestamp() - float(candles[-1]["timestamp"]) <= seconds


def next_entry() -> str:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return (now + timedelta(minutes=5 - now.minute % 5)).isoformat()


def telegram(text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHANNEL_ID, "text": text},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected message: {payload.get('description', 'unknown error')}")


def format_signal(result: dict, entry_at: str) -> str:
    direction = result["decision"]
    reasons = result.get("reasons", [])[-5:]
    lines = [
        "⚡️ NEXUS I.A TRADER ⚡️",
        "🤖 Análise automática — TESTE",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"💱 ATIVO\n{result['symbol']}",
        "",
        f"📊 DIREÇÃO\n{'🟢' if direction == 'CALL' else '🔴'} {direction}",
        "",
        f"⏰ ENTRADA\n{entry_at[11:16]} UTC",
        "⌛ EXPIRAÇÃO\nM5",
        "",
        f"🧠 Confiança: {result.get('confidence', 0)}/100",
        f"M1: {result.get('m1_decision')} · M5: {result.get('decision')} · M15: {result.get('m15_decision')} · H1: {result.get('h1_decision')}",
        "",
        "Motivos:",
        *[f"• {reason}" for reason in reasons],
        "",
        "Fonte: IQ Option exclusivamente.",
        "Modo TESTE — nenhuma ordem foi executada.",
    ]
    return "\n".join(lines)


def main() -> None:
    if not EMAIL or not PASSWORD:
        raise RuntimeError("IQ Option credentials are missing")
    assets = available_signal_assets()
    if not assets:
        raise RuntimeError("IQ Option returned no open candle assets")
    # Keep OTC assets in the scan when IQ reports them as open.
    assets = sorted(assets, key=lambda symbol: (not symbol.endswith("-OTC"), symbol))[:MAX_ASSETS]
    print(f"IQ_OPEN_ASSETS={len(assets)}")
    sent = 0
    for symbol in assets:
        try:
            m1 = fetch_iq_candles(symbol, "1m", 80)
            m5 = fetch_iq_candles(symbol, "5m", 80)
            m15 = fetch_iq_candles(symbol, "15m", 80)
            h1 = fetch_iq_candles(symbol, "1h", 80)
            if not (fresh(m1, 180) and fresh(m5, 600) and fresh(m15, 2100) and fresh(h1, 7200)):
                print(f"{symbol}=SKIP_STALE")
                continue
            result = analyze_with_confirmation(symbol, m5, m15, h1, m1)
            eligible = bool(result.get("confluence_ok")) and bool(result.get("rsi_entry_ok", True)) and result.get("confidence", 0) >= MIN_CONFIDENCE
            print(f"{symbol}={result.get('decision')} confidence={result.get('confidence', 0)} eligible={eligible}")
            if eligible:
                telegram(format_signal(result, next_entry()))
                sent += 1
        except Exception as error:
            print(f"{symbol}=ERROR {type(error).__name__}: {str(error)[:160]}")
    print(f"SIGNALS_SENT={sent}")


if __name__ == "__main__":
    main()
