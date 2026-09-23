import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

try:
    from .market_data import fetch_candles, is_fresh, market_data_source, normalize_symbol
    from .paper_journal import close_signal, create_signal, format_history, format_ranking, format_result, format_session_summary, format_signal, format_statistics, get_telegram_file_id, mark_result_delivered, pending_result_deliveries, pending_signal_status, ranking, recent_signals, save_telegram_file_id, session_statistics, settle_pending, statistics
    from .signal_engine import analyze_with_confirmation, format_analysis
except ImportError:
    from market_data import fetch_candles, is_fresh, market_data_source, normalize_symbol
    from paper_journal import close_signal, create_signal, format_history, format_ranking, format_result, format_session_summary, format_signal, format_statistics, get_telegram_file_id, mark_result_delivered, pending_result_deliveries, pending_signal_status, ranking, recent_signals, save_telegram_file_id, session_statistics, settle_pending, statistics
    from signal_engine import analyze_with_confirmation, format_analysis

load_dotenv()

app = Flask(__name__)

BOT_MODE = os.getenv("BOT_MODE", "TESTE").upper()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@NexusTraderIA").strip()
PORT = int(os.getenv("PORT", "10000"))
AUTO_SIGNALS_ENABLED = os.getenv("AUTO_SIGNALS_ENABLED", "false").lower() == "true"
# M5 strategy: refresh once per minute, never once per second.
AUTO_SIGNAL_INTERVAL = 60
AUTO_SIGNAL_MIN_SCORE = int(os.getenv("AUTO_SIGNAL_MIN_SCORE", "80"))
AUTO_SIGNAL_MAX_DAILY = int(os.getenv("AUTO_SIGNAL_MAX_DAILY", "6"))
AUTO_SUMMARY_INTERVAL = int(os.getenv("AUTO_SUMMARY_INTERVAL", "7200"))
AUTO_SYMBOLS = tuple(item.strip() for item in os.getenv("AUTO_SYMBOLS", "EUR/USD,EUR/JPY,USD/JPY,GBP/USD,GBP/JPY,AUD/USD,USD/CAD").split(",") if item.strip())
RESULT_IMAGE_PATHS = {
    "WIN": os.getenv("WIN_IMAGE_PATH", os.path.join(os.path.dirname(__file__), "assets", "win.png")),
    "LOSS": os.getenv("LOSS_IMAGE_PATH", os.path.join(os.path.dirname(__file__), "assets", "loss.png")),
}
RESULT_STICKER_IDS = {
    "WIN": os.getenv("WIN_STICKER_FILE_ID", "").strip(),
    "LOSS": os.getenv("LOSS_STICKER_FILE_ID", "").strip(),
}

state = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_update": None,
    "last_message": None,
    "auto_last_sent": {},
    "auto_sent_today": 0,
    "auto_sent_date": None,
    "auto_last_scan": None,
    "auto_scan_errors": 0,
    "auto_last_error": None,
    "last_settlement": None,
    "settled_count": 0,
    "settlement_error": None,
    "settlement_last_check": None,
    "result_file_ids": {},
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


def send_result(item: dict, chat_id: str | None = None) -> bool:
    """Send the settlement caption with the matching WIN/LOSS artwork."""
    outcome = item.get("outcome", "").upper()
    sticker_id = RESULT_STICKER_IDS.get(outcome)
    if BOT_TOKEN and sticker_id:
        try:
            sticker_response = requests.post(
                telegram_url("sendSticker"),
                json={"chat_id": chat_id or CHANNEL_ID, "sticker": sticker_id},
                timeout=30,
            )
            sticker_response.raise_for_status()
            send_message(format_result(item), chat_id)
            state["last_message"] = datetime.now(timezone.utc).isoformat()
            return True
        except requests.RequestException as error:
            state["settlement_error"] = type(error).__name__
            return False
    image_path = RESULT_IMAGE_PATHS.get(outcome)
    if not BOT_TOKEN or not image_path or not os.path.isfile(image_path):
        state["settlement_error"] = f"imagem_{outcome.lower()}_ausente"
        return False
    for attempt in range(3):
        try:
            file_id = state["result_file_ids"].get(outcome) or get_telegram_file_id(outcome)
            if file_id:
                response = requests.post(
                    telegram_url("sendPhoto"),
                    json={"chat_id": chat_id or CHANNEL_ID, "photo": file_id, "caption": format_result(item)},
                    timeout=30,
                )
            else:
                with open(image_path, "rb") as image_file:
                    response = requests.post(
                        telegram_url("sendPhoto"),
                        data={"chat_id": chat_id or CHANNEL_ID, "caption": format_result(item)},
                        files={"photo": (os.path.basename(image_path), image_file, "image/png")},
                        timeout=30,
                    )
            response.raise_for_status()
            if not file_id:
                result = response.json().get("result", {})
                photos = result.get("photo", [])
                if photos:
                    file_id = photos[-1].get("file_id")
                    state["result_file_ids"][outcome] = file_id
                    if file_id:
                        save_telegram_file_id(outcome, file_id)
            state["last_message"] = datetime.now(timezone.utc).isoformat()
            return True
        except (OSError, requests.RequestException) as error:
            state["settlement_error"] = type(error).__name__
            if attempt < 2:
                time.sleep(2)
    return False


def build_analysis(symbol: str) -> tuple[dict, dict]:
    candles_m1 = fetch_candles(symbol, interval="1m", range_="1d", count=80)
    source_m1 = market_data_source()
    candles_m5 = fetch_candles(symbol, interval="5m", range_="1d", count=80)
    source_m5 = market_data_source()
    candles_m15 = fetch_candles(symbol, interval="15m", range_="5d", count=80)
    source_m15 = market_data_source()
    candles_h1 = fetch_candles(symbol, interval="1h", range_="60d", count=80)
    source_h1 = market_data_source()
    if not is_fresh(candles_m1, 3 * 60):
        raise RuntimeError("candles M1 atrasados")
    if not is_fresh(candles_m5, 10 * 60):
        raise RuntimeError("candles M5 atrasados")
    if not is_fresh(candles_m15, 35 * 60):
        raise RuntimeError("candles M15 atrasados")
    if not is_fresh(candles_h1, 2 * 60 * 60):
        raise RuntimeError("candles H1 atrasados")
    result = analyze_with_confirmation(symbol, candles_m5, candles_m15, candles_h1, candles_m1)
    result["source"] = ", ".join(dict.fromkeys((source_m1, source_m5, source_m15, source_h1)))
    return result, {}


def auto_scan_loop() -> None:
    """Publish only high-score paper signals; never sends broker orders."""
    if not BOT_TOKEN or not AUTO_SIGNALS_ENABLED:
        return
    while True:
        for symbol in AUTO_SYMBOLS:
            try:
                state["auto_last_scan"] = datetime.now(timezone.utc).isoformat()
                result, _ = build_analysis(normalize_symbol(symbol))
                now = datetime.now(timezone.utc)
                last_sent = state["auto_last_sent"].get(result["symbol"])
                cooldown_ok = not last_sent or now - last_sent >= timedelta(minutes=20)
                eligible = result.get("confluence_ok", False) and result["score"] >= AUTO_SIGNAL_MIN_SCORE
                today = now.date().isoformat()
                if state["auto_sent_date"] != today:
                    state["auto_sent_date"] = today
                    state["auto_sent_today"] = 0
                daily_limit_ok = state["auto_sent_today"] < AUTO_SIGNAL_MAX_DAILY
                if eligible and cooldown_ok and daily_limit_ok:
                    signal = create_signal(result)
                    if signal.get("_duplicate"):
                        continue
                    send_message(
                        format_signal(signal),
                    )
                    state["auto_last_sent"][result["symbol"]] = now
                    state["auto_sent_today"] += 1
            except Exception as error:
                state["auto_scan_errors"] += 1
                state["auto_last_error"] = type(error).__name__
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
            state["settlement_last_check"] = datetime.now(timezone.utc).isoformat()
            settled = settle_pending(price_lookup)
            delivered = 0
            for item in pending_result_deliveries():
                if send_result(item) and mark_result_delivered(item["id"]):
                    delivered += 1
            if settled or delivered:
                state["last_settlement"] = datetime.now(timezone.utc).isoformat()
                state["settled_count"] += len(settled)
            state["settlement_error"] = None
        except Exception as error:
            state["settlement_error"] = type(error).__name__
        time.sleep(60)


def session_summary_loop() -> None:
    """Publish a rolling two-hour paper-trading summary to the channel."""
    if not BOT_TOKEN:
        return
    while True:
        time.sleep(max(900, AUTO_SUMMARY_INTERVAL))
        try:
            send_message(format_session_summary(session_statistics(2)))
        except Exception:
            continue


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
        send_message("NEXUS IA TRADER\n\nO módulo de notícias está desativado temporariamente.", chat_id)
    elif text.startswith("/sinal"):
        requested = text.removeprefix("/sinal").strip() or "EUR/JPY"
        symbol = normalize_symbol(requested)
        try:
            result, _ = build_analysis(symbol)
            if not result.get("confluence_ok", False):
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
    elif text == "/ranking":
        send_message(format_ranking(ranking()), chat_id)
    elif text == "/sessao":
        send_message(format_session_summary(session_statistics(2)), chat_id)
    elif text == "/ajuda":
        send_message(
            "NEXUS IA TRADER\n\n"
            "/analisar EUR/JPY — análise M5/M15/H1\n"
            "/sinal EUR/JPY — cria registro PAPER TRADING\n"
            "/resultado ID WIN|LOSS|VOID — fecha simulação\n"
            "/historico — lista simulações\n\n"
            "/stats [ATIVO] — mostra estatísticas gerais ou por ativo\n\n"
            "/ranking — compara os ativos da amostra\n\n"
            "/sessao — resumo das últimas 2 horas\n\n"
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
            "auto_sent_today": state["auto_sent_today"],
            "auto_last_scan": state["auto_last_scan"],
            "auto_scan_errors": state["auto_scan_errors"],
            "auto_last_error": state["auto_last_error"],
            "last_settlement": state["last_settlement"],
            "settlement_last_check": state["settlement_last_check"],
            "settled_count": state["settled_count"],
            "settlement_error": state["settlement_error"],
            "paper_statistics": statistics(),
            "pending_signals": pending_signal_status(),
            "undelivered_results": len(pending_result_deliveries()),
        }
    )


@app.get("/health/data")
def health_data():
    """Verify a live candle without exposing secrets or prices."""
    symbol = "EUR/USD"
    try:
        candles = fetch_candles(symbol, interval="5m", range_="1d", count=1)
        return jsonify({
            "status": "ok",
            "symbol": symbol,
            "source": market_data_source(),
            "candle_available": bool(candles),
            "candle_fresh": is_fresh(candles, 10 * 60),
            "twelve_data_configured": bool(os.getenv("TWELVEDATA_API_KEY", "").strip()),
        })
    except Exception as error:
        return jsonify({
            "status": "error",
            "symbol": symbol,
            "detail": type(error).__name__,
            "twelve_data_configured": bool(os.getenv("TWELVEDATA_API_KEY", "").strip()),
        }), 503


if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=polling_loop, daemon=True).start()
        threading.Thread(target=settlement_loop, daemon=True).start()
        threading.Thread(target=session_summary_loop, daemon=True).start()
        if AUTO_SIGNALS_ENABLED:
            threading.Thread(target=auto_scan_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
