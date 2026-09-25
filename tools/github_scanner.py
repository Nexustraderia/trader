import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from app.iq_data import available_signal_assets, fetch_iq_candles
from app.signal_engine import analyze_with_confirmation

CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@NexusTraderIA").strip()
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
EMAIL = os.environ["IQ_OPTION_EMAIL"].strip()
PASSWORD = os.environ["IQ_OPTION_PASSWORD"]
MIN_CONFIDENCE = int(os.getenv("AUTO_SIGNAL_MIN_CONFIDENCE", "80"))
MAX_ASSETS = int(os.getenv("MAX_SCAN_ASSETS", "12"))
STATE_PATH = Path(os.getenv("SCANNER_STATE_PATH", "runtime_state.json"))
BRASILIA = ZoneInfo("America/Sao_Paulo")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def fresh(candles: list[dict], seconds: int) -> bool:
    return bool(candles) and now_utc().timestamp() - float(candles[-1]["timestamp"]) <= seconds


def next_entry() -> datetime:
    current = now_utc().replace(second=0, microsecond=0)
    return current + timedelta(minutes=5 - current.minute % 5)


def candle_at_or_before(symbol: str, target: datetime) -> float:
    candles = fetch_iq_candles(symbol, "5m", 600)
    eligible = [c for c in candles if float(c.get("timestamp", 0)) <= target.timestamp()]
    if not eligible:
        raise RuntimeError(f"No M5 candle at or before {target.isoformat()}")
    candle = eligible[-1]
    if target.timestamp() - float(candle["timestamp"]) > 10 * 60:
        raise RuntimeError("Historical M5 candle is stale")
    return float(candle["close"])


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"pending": [], "settled": []}
    try:
        data = json.loads(STATE_PATH.read_text())
        return {"pending": list(data.get("pending", [])), "settled": list(data.get("settled", []))}
    except (OSError, ValueError, TypeError):
        return {"pending": [], "settled": []}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def format_signal(result: dict, entry_at: datetime) -> str:
    local = entry_at.astimezone(BRASILIA)
    reasons = result.get("reasons", [])[-5:]
    return "\n".join([
        "⚡️ NEXUS I.A TRADER ⚡️",
        "🤖 Análise automática — TESTE",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"💱 ATIVO\n{result['symbol']}",
        "",
        f"📊 DIREÇÃO\n{'🟢' if result['decision'] == 'CALL' else '🔴'} {result['decision']}",
        "",
        f"⏰ ENTRADA\n{local.strftime('%H:%M')} (UTC−3 Brasília)",
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
    ])


def format_result(item: dict, outcome: str) -> str:
    local = datetime.fromisoformat(item["entry_at"]).astimezone(BRASILIA)
    label = {"WIN": "✅ WIN", "LOSS": "🔴 LOSS", "VOID": "⚪ VOID"}[outcome]
    return "\n".join([
        "⚡️ NEXUS I.A TRADER ⚡️",
        "📊 Resultado do paper trading",
        "",
        f"💱 Ativo: {item['symbol']}",
        f"📍 Direção: {item['direction']}",
        f"⏰ Entrada: {local.strftime('%H:%M')} (UTC−3 Brasília)",
        "⌛ Expiração: M5",
        "",
        label,
        "",
        "Fonte: IQ Option exclusivamente.",
        "Modo TESTE — nenhuma ordem foi executada.",
    ])


def settle_pending(state: dict) -> None:
    remaining = []
    for item in state["pending"]:
        expiry = datetime.fromisoformat(item["expires_at"])
        if expiry > now_utc():
            remaining.append(item)
            continue
        try:
            if item.get("entry_price") is None:
                item["entry_price"] = candle_at_or_before(item["symbol"], datetime.fromisoformat(item["entry_at"]))
            exit_price = candle_at_or_before(item["symbol"], expiry)
            entry_price = float(item["entry_price"])
            if exit_price == entry_price:
                outcome = "VOID"
            elif (item["direction"] == "CALL" and exit_price > entry_price) or (item["direction"] == "PUT" and exit_price < entry_price):
                outcome = "WIN"
            else:
                outcome = "LOSS"
            item["exit_price"] = exit_price
            item["outcome"] = outcome
            state["settled"].append(item)
            telegram(format_result(item, outcome))
            print(f"RESULT {item['symbol']}={outcome}")
        except Exception as error:
            item["settlement_error"] = f"{type(error).__name__}: {str(error)[:160]}"
            remaining.append(item)
            print(f"SETTLEMENT_ERROR {item['symbol']} {item['settlement_error']}")
    state["pending"] = remaining
    state["settled"] = state["settled"][-100:]


def main() -> None:
    if not EMAIL or not PASSWORD:
        raise RuntimeError("IQ Option credentials are missing")
    state = load_state()
    settle_pending(state)
    assets = available_signal_assets()
    if not assets:
        raise RuntimeError("IQ Option returned no open candle assets")
    assets = sorted(assets, key=lambda symbol: (not symbol.endswith("-OTC"), symbol))[:MAX_ASSETS]
    print(f"IQ_OPEN_ASSETS={len(assets)}")
    entry = next_entry()
    sent = 0
    pending_keys = {(x["symbol"], x["entry_at"]) for x in state["pending"]}
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
            key = (symbol, entry.isoformat())
            if eligible and key not in pending_keys:
                item = {
                    "symbol": symbol,
                    "direction": result["decision"],
                    "score": int(result["score"]),
                    "confidence": int(result.get("confidence", 0)),
                    "entry_at": entry.isoformat(),
                    "expires_at": (entry + timedelta(minutes=5)).isoformat(),
                    "entry_price": float(result["price"]),
                }
                telegram(format_signal(result, entry))
                state["pending"].append(item)
                pending_keys.add(key)
                sent += 1
        except Exception as error:
            print(f"{symbol}=ERROR {type(error).__name__}: {str(error)[:160]}")
    save_state(state)
    print(f"SIGNALS_SENT={sent}")
    print(f"PENDING_RESULTS={len(state['pending'])}")


if __name__ == "__main__":
    main()
