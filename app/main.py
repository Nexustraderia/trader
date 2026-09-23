import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

try:
    from .market_data import fetch_candles, is_fresh, normalize_symbol
    from .news_sentinel import fetch_news, format_news, should_block
    from .paper_journal import close_signal, create_signal, format_history, format_signal, format_statistics, recent_signals, settle_pending, statistics
    from .signal_engine import analyze_with_confirmation, format_analysis
except ImportError:
    from market_data import fetch_candles, is_fresh, normalize_symbol
    from news_sentinel import fetch_news, format_news, should_block
    from paper_journal import close_signal, create_signal, format_history, format_signal, format_statistics, recent_signals, settle_pending, statistics
    from signal_engine import analyze_with_confirmation, format_analysis

load_dotenv()

app = Flask(__name__)

BOT_MODE = os.getenv("BOT_MODE", "TESTE").upper()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@NexusTraderIA").strip()
PORT = int(os.getenv("PORT", "10000"))
AUTO_SIGNALS_ENABLED = os.getenv("AUTO_SIGNALS_ENABLED", "false").lower() == "true"
AUTO_SIGNAL_INTERVAL = int(os.getenv("AUTO_SIGNAL_INTERVAL", "300"))
AUTO_SIGNAL_MIN_SCORE = int(os.getenv("AUTO_SIGNAL_MIN_SCORE", "80"))
AUTO_SIGNAL_MAX_DAILY = int(os.getenv("AUTO_SIGNAL_MAX_DAILY", "6"))
AUTO_SYMBOLS = tuple(item.strip() for item in os.getenv("AUTO_SYMBOLS", "EUR/JPY,EUR/USD,GBP/USD,XAU/USD").split(",") if item.strip())

state = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_update": None,
    "last_message": None,
    "auto_last_sent": {},
    "auto_sent_today": 0,
    "auto_sent_date": None,
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


def build_analysis(symbol: str) -> tuple[dict, dict]:
    candles_m5 = fetch_candles(symbol, interval="5m", range_="1d", count=80)
    candles_m15 = fetch_candles(symbol, interval="15m", range_="5d", count=80)
    candles_h1 = fetch_candles(symbol, interval="1h", range_="60d", count=80)
    if not is_fresh(candles_m5, 10 * 60):
        raise RuntimeError("candles M5 atrasados")
    if not is_fresh(candles_m15, 35 * 60):
        raise RuntimeError("candles M15 atrasados")
    if not is_fresh(candles_h1, 2 * 60 * 60):
        raise RuntimeError("candles H1 atrasados")
    result = analyze_with_confirmation(symbol, candles_m5, candles_m15, candles_h1)
    news = fetch_news(symbol)
    result["news_status"] = news["status"]
    if should_block(news):
        result["decision"] = "AGUARDAR"
        result["score"] = min(result["score"], 40)
        result["reasons"].append("NEXUS SENTINEL detectou notícia macro de alto impacto; sinal bloqueado")
    return result, news


def auto_scan_loop() -> None:
    """Publish only high-score paper signals; never sends broker orders."""
    if not BOT_TOKEN or not AUTO_SIGNALS_ENABLED:
        return
    while True:
        for symbol in AUTO_SYMBOLS:
            try:
                result, _ = build_analysis(normalize_symbol(symbol))
                now = datetime.now(timezone.utc)
                last_sent = state["auto_last_sent"].get(result["symbol"])
                cooldown_ok = not last_sent or now - last_sent >= timedelta(minutes=20)
                eligible = result["decision"] in ("CALL", "PUT") and result["score"] >= AUTO_SIGNAL_MIN_SCORE
                today = now.date().isoformat()
                if state["auto_sent_date"] != today:
                    state["auto_sent_date"] = today
                    state["auto_sent_today"] = 0
                daily_limit_ok = state["auto_sent_today"] < AUTO_SIGNAL_MAX_DAILY
                if eligible and cooldown_ok and daily_limit_ok:
                    signal = create_signal(result)
                    send_message(
                        format_signal(signal) + "\n\nPublicação automática TESTE — sem ordem real.",
                    )
                    state["auto_last_sent"][result["symbol"]] = now
                    state["auto_sent_today"] += 1
            except Exception:
                continue
        time.sleep(max(60, AUTO_SIGNAL_INTERVAL))


def price_lookup(symbol: str) -> float:
    candles = fetch_candles(symbol, interval="5m", range_="1d", count=1)
    if not candles:
        raise ValueError("preço indisponível")
    return float(candles[-1]["close"])


def settlement_loop() -> None:
    if not BOT_TOKEN:
        return
    while True:
        try:
            settled = settle_pending(price_lookup)
            for item in settled:
                send_message(
                    "NEXUS IA TRADER — RESULTADO SIMULADO\n\n"
                    f"ID: {item['id']}\nAtivo: {item['symbol']}\n"
                    f"Direção: {item['direction']}\nResultado M5: {item['outcome']}\n"
                    f"Entrada: {item['entry_price']}\nSaída: {item['exit_price']}\n\n"
                    "PAPER TRADING — sem ordem real."
                )
        except Exception:
            pass
        time.sleep(60)


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
    elif text.startswith("/noticias"):
        requested = text.removeprefix("/noticias").strip() or "EUR/JPY"
        symbol = normalize_symbol(requested)
        try:
            send_message(format_news(fetch_news(symbol)), chat_id)
        except Exception as error:
            send_message(
                "NEXUS SENTINEL\n\nStatus: AGUARDAR\n"
                f"Não foi possível consultar as notícias agora ({type(error).__name__}).",
                chat_id,
            )
    elif text.startswith("/sinal"):
        requested = text.removeprefix("/sinal").strip() or "EUR/JPY"
        symbol = normalize_symbol(requested)
        try:
            result, _ = build_analysis(symbol)
            if result["decision"] not in ("CALL", "PUT"):
                send_message(
                    format_analysis(result) + "\n\nNenhum sinal simulado criado: condição insuficiente.",
                    chat_id,
                )
            else:
                send_message(format_signal(create_signal(result)), chat_id)
        except Exception as error:
            send_message(f"NEXUS IA TRADER\n\nSinal simulado indisponível: {type(error).__name__}", chat_id)
    elif text.startswith("/resultado"):
        parts = text.split()
        if len(parts) != 3 or not close_signal(parts[1], parts[2]):
            send_message("Uso: /resultado ID WIN|LOSS|VOID", chat_id)
        else:
            send_message(f"Resultado do sinal {parts[1].upper()} registrado como {parts[2].upper()}.", chat_id)
    elif text == "/historico":
        send_message(format_history(recent_signals()), chat_id)
    elif text.startswith("/stats"):
        requested = text.removeprefix("/stats").strip()
        symbol = normalize_symbol(requested) if requested else None
        send_message(format_statistics(statistics(symbol), symbol), chat_id)
    elif text == "/ajuda":
        send_message(
            "NEXUS IA TRADER\n\n"
            "/analisar EUR/JPY — análise M5/M15/H1\n"
            "/noticias EUR/JPY — filtro macroeconômico\n"
            "/sinal EUR/JPY — cria registro PAPER TRADING\n"
            "/resultado ID WIN|LOSS|VOID — fecha simulação\n"
            "/historico — lista simulações\n\n"
            "/stats [ATIVO] — mostra estatísticas gerais ou por ativo\n\n"
            "Nenhum comando envia ordens reais.",
            chat_id,
        )
    elif text.startswith("/analisar"):
        requested = text.removeprefix("/analisar").strip() or "EUR/JPY"
        symbol = normalize_symbol(requested)
        try:
            result, _ = build_analysis(symbol)
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
            "auto_signals_enabled": AUTO_SIGNALS_ENABLED,
            "auto_signal_min_score": AUTO_SIGNAL_MIN_SCORE,
            "auto_signal_max_daily": AUTO_SIGNAL_MAX_DAILY,
            "auto_symbols": AUTO_SYMBOLS,
        }
    )


if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=polling_loop, daemon=True).start()
        threading.Thread(target=settlement_loop, daemon=True).start()
        if AUTO_SIGNALS_ENABLED:
            threading.Thread(target=auto_scan_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
