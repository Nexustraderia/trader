import os
import threading
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

from market_data import fetch_candles, normalize_symbol
from signal_engine import analyze_with_confirmation, format_analysis

load_dotenv()

app = Flask(__name__)

BOT_MODE = os.getenv("BOT_MODE", "TESTE").upper()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@NexusTraderIA").strip()
PORT = int(os.getenv("PORT", "10000"))

state = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_update": None,
    "last_message": None,
}


def telegram_url(method: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def send_message(text: str, chat_id: str | None = None) -> bool:
    """Send a Telegram message only when a token is configured."""
    if not BOT_TOKEN:
        return False
    response = requests.post(
        telegram_url("sendMessage"),
        json={"chat_id": chat_id or CHANNEL_ID, "text": text},
        timeout=20,
    )
    response.raise_for_status()
    state["last_message"] = datetime.now(timezone.utc).isoformat()
    return True


def handle_update(update: dict) -> None:
    message = update.get("message", {})
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat", {}).get("id")

    if text == "/start":
        send_message(
            "NEXUS IA TRADER\n\n"
            "Status: ONLINE\n"
            f"Modo: {BOT_MODE}\n"
            "Análises automáticas: em preparação\n"
            "Ordens automáticas: DESATIVADAS",
            chat_id,
        )
    elif text == "/status":
        send_message(
            f"NEXUS IA TRADER\nStatus: ONLINE\nModo: {BOT_MODE}",
            chat_id,
        )
    elif text.startswith("/analisar"):
        requested = text.removeprefix("/analisar").strip() or "EUR/JPY"
        symbol = normalize_symbol(requested)
        try:
            candles_m5 = fetch_candles(symbol, interval="5m", range_="1d", count=80)
            candles_m15 = fetch_candles(symbol, interval="15m", range_="5d", count=80)
            result = analyze_with_confirmation(symbol, candles_m5, candles_m15)
            send_message(format_analysis(result), chat_id)
        except Exception as error:
            send_message(
                "NEXUS IA TRADER\n\n"
                f"Não foi possível analisar {symbol} agora.\n"
                "Status: AGUARDAR\n"
                f"Detalhe técnico: {type(error).__name__}",
                chat_id,
            )


def polling_loop() -> None:
    """Minimal long-polling loop for private testing."""
    if not BOT_TOKEN:
        return

    offset = 0
    while True:
        try:
            response = requests.get(
                telegram_url("getUpdates"),
                params={"timeout": 25, "offset": offset},
                timeout=35,
            )
            response.raise_for_status()
            updates = response.json().get("result", [])
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                state["last_update"] = datetime.now(timezone.utc).isoformat()
                handle_update(update)
        except Exception:
            time.sleep(5)


@app.get("/")
def index():
    return "NEXUS IA TRADER online"


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "online",
            "mode": BOT_MODE,
            "telegram_configured": bool(BOT_TOKEN),
            "channel_configured": bool(CHANNEL_ID),
            "started_at": state["started_at"],
            "last_update": state["last_update"],
            "last_message": state["last_message"],
        }
    )


if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=polling_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
