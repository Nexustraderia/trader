import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

try:
    from .db import backend_name
    from .iq_data import IQ_SYMBOLS, available_asset_modes, available_iq_assets, available_signal_assets, cached_otc_open_assets, cached_signal_assets, is_iq_asset_open
    from .market_data import fetch_candles, is_fresh, market_data_diagnostics, market_data_source, normalize_symbol
    from .paper_journal import capture_entry_prices, close_signal, create_signal, format_history, format_ranking, format_result, format_result_batch, format_session_summary, format_signal, format_statistics, mark_result_batch, mark_result_delivered, next_result_batch, pending_result_deliveries, pending_signal_status, ranking, recent_signals, reset_history_if_requested, session_statistics, settle_pending, statistics
    from .signal_engine import analyze_with_confirmation, format_analysis
except ImportError:
    from db import backend_name
    from iq_data import IQ_SYMBOLS, available_asset_modes, available_iq_assets, available_signal_assets, cached_otc_open_assets, cached_signal_assets, is_iq_asset_open
    from market_data import fetch_candles, is_fresh, market_data_diagnostics, market_data_source, normalize_symbol
    from paper_journal import capture_entry_prices, close_signal, create_signal, format_history, format_ranking, format_result, format_result_batch, format_session_summary, format_signal, format_statistics, mark_result_batch, mark_result_delivered, next_result_batch, pending_result_deliveries, pending_signal_status, ranking, recent_signals, reset_history_if_requested, session_statistics, settle_pending, statistics
    from signal_engine import analyze_with_confirmation, format_analysis

load_dotenv()

HISTORY_RESET_APPLIED = reset_history_if_requested()

app = Flask(__name__)

BOT_MODE = os.getenv("BOT_MODE", "TESTE").upper()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@NexusTraderIA").strip()
IQ_OPTION_AFFILIATE_URL = "https://affiliate.iqoption.net/redir/?aff=232843&aff_model=revenue&afftrack="
PORT = int(os.getenv("PORT", "10000"))
AUTO_SIGNALS_ENABLED = os.getenv("AUTO_SIGNALS_ENABLED", "false").lower() == "true"
# M5 strategy: refresh once per minute, never once per second.
AUTO_SIGNAL_INTERVAL = 60
# Legacy technical score is directional: CALL is high and PUT is low. Use the
# normalized confidence so a high-quality PUT is not rejected as "low score".
# Balanced selectivity: keep full M5/M15/H1/M1 confluence while allowing
# high-quality setups that score 80+ to be published.
AUTO_SIGNAL_MIN_CONFIDENCE = int(os.getenv("AUTO_SIGNAL_MIN_CONFIDENCE", os.getenv("AUTO_SIGNAL_MIN_SCORE", "80")))
# Signals are continuous. The legacy AUTO_SIGNAL_MAX_DAILY variable is kept
# only for deployment compatibility and is intentionally ignored.
AUTO_SIGNAL_MAX_DAILY = 0
AUTO_SUMMARY_INTERVAL = int(os.getenv("AUTO_SUMMARY_INTERVAL", "3600"))
AUTO_INCLUDE_IQ_ASSETS = os.getenv("AUTO_INCLUDE_IQ_ASSETS", "true").lower() == "true"
AUTO_OTC_ONLY = os.getenv("AUTO_OTC_ONLY", "false").lower() == "true"
AUTO_REQUIRE_FULL_ALIGNMENT = os.getenv("AUTO_REQUIRE_FULL_ALIGNMENT", "true").lower() == "true"
state = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_update": None,
    "last_message": None,
    "auto_last_sent": {},
    "auto_sent_today": 0,
    "auto_sent_date": None,
    "auto_last_scan": None,
    "auto_cycle_started": None,
    "auto_cycle_completed": None,
    "auto_cycle_processed": 0,
    "auto_cycle_total": 0,
    "auto_current_symbol": None,
    "auto_symbols": [],
    "auto_last_decisions": {},
    "auto_scan_errors": 0,
    "auto_last_error": None,
    "iq_catalog_available": False,
    "iq_catalog_last_refresh": None,
    "iq_catalog_error": None,
    "iq_open_assets": [],
    "iq_open_otc": [],
    "last_settlement": None,
    "settled_count": 0,
    "settlement_error": None,
    "settlement_last_check": None,
}


def telegram_url(method: str) -> str:
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def send_message(text: str, chat_id: str | None = None, reply_markup: dict | None = None) -> bool:
    """Send a Telegram message only when a token is configured."""
    if not BOT_TOKEN:
        return False
    response = requests.post(
        telegram_url("sendMessage"),
        json={"chat_id": chat_id or CHANNEL_ID, "text": text, **({"reply_markup": reply_markup} if reply_markup else {})},
        timeout=20,
    )
    response.raise_for_status()
    state["last_message"] = datetime.now(timezone.utc).isoformat()
    return True


def signal_reply_markup() -> dict:
    return {"inline_keyboard": [[{"text": "CLIQUE AQUI", "url": IQ_OPTION_AFFILIATE_URL}]]}


def send_signal(signal: dict, chat_id: str | None = None) -> bool:
    """Send the formatted signal with its affiliate button."""
    return send_message(format_signal(signal), chat_id, signal_reply_markup())


def send_result(item: dict, chat_id: str | None = None) -> bool:
    """Send only the text result; no image attachment is used."""
    return send_message(format_result(item), chat_id)


def build_analysis(symbol: str) -> tuple[dict, dict]:
    if not is_iq_asset_open(symbol):
        raise RuntimeError("IQ Option asset closed")
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
        state["auto_cycle_started"] = datetime.now(timezone.utc).isoformat()
        state["auto_cycle_completed"] = None
        state["auto_cycle_processed"] = 0
        # IQ Option is the sole provider. Without a fresh IQ catalog there is
        # no scan universe and no signal is generated.
        if AUTO_INCLUDE_IQ_ASSETS:
            # Keep normal IQ pairs testable while the slower OTC/open-catalog
            # refresh is running. No external market-data fallback is used.
            scan_symbols = list(state["iq_open_assets"]) if state["iq_catalog_available"] else []
            if AUTO_OTC_ONLY:
                scan_symbols = [symbol for symbol in scan_symbols if symbol.endswith("-OTC")]
        else:
            scan_symbols = []
        state["auto_symbols"] = scan_symbols
        state["auto_cycle_total"] = len(scan_symbols)
        state["auto_current_symbol"] = None
        state["auto_last_decisions"] = {}
        for symbol in scan_symbols:
            state["auto_current_symbol"] = symbol
            try:
                state["auto_last_scan"] = datetime.now(timezone.utc).isoformat()
                result, _ = build_analysis(normalize_symbol(symbol))
                state["auto_last_decisions"][result["symbol"]] = {
                    "decision": result.get("decision"),
                    "score": result.get("score"),
                    "m1": result.get("m1_decision"),
                    "m5": result.get("decision"),
                    "m15": result.get("m15_decision"),
                    "h1": result.get("h1_decision"),
                    "confidence": result.get("confidence", 50),
                    "confluence_ok": result.get("confluence_ok", False),
                }
                now = datetime.now(timezone.utc)
                last_sent = state["auto_last_sent"].get(result["symbol"])
                cooldown_ok = not last_sent or now - last_sent >= timedelta(minutes=20)
                eligible = (
                    result.get("confluence_ok", False)
                    and result.get("rsi_entry_ok", True)
                    and result.get("confidence", 0) >= AUTO_SIGNAL_MIN_CONFIDENCE
                )
                if AUTO_REQUIRE_FULL_ALIGNMENT:
                    eligible = eligible and all(
                        result.get(key) == result.get("decision")
                        for key in ("m1_decision", "m15_decision", "h1_decision")
                    )
                today = now.date().isoformat()
                if state["auto_sent_date"] != today:
                    state["auto_sent_date"] = today
                    state["auto_sent_today"] = 0
                # No daily cap: quality remains protected by confluence,
                # confidence, per-asset cooldown, and journal deduplication.
                daily_limit_ok = True
                if eligible and cooldown_ok and daily_limit_ok:
                    signal = create_signal(result)
                    if signal.get("_duplicate"):
                        continue
                    send_signal(signal)
                    state["auto_last_sent"][result["symbol"]] = now
                    state["auto_sent_today"] += 1
            except Exception as error:
                if "IQ Option OTC catalog unavailable" in str(error) or "IQ Option asset not open" in str(error) or "IQ Option asset closed" in str(error):
                    continue
                state["auto_scan_errors"] += 1
                state["auto_last_error"] = f"{type(error).__name__}: {str(error)[:160]}"
                continue
            finally:
                state["auto_cycle_processed"] += 1
        state["auto_current_symbol"] = None
        state["auto_cycle_completed"] = datetime.now(timezone.utc).isoformat()
        time.sleep(max(60, AUTO_SIGNAL_INTERVAL))


def asset_catalog_loop() -> None:
    """Refresh IQ's open-asset catalog outside the time-sensitive scan loop."""
    while True:
        try:
            assets = available_signal_assets()
            state["iq_catalog_available"] = True
            state["iq_catalog_last_refresh"] = datetime.now(timezone.utc).isoformat()
            state["iq_catalog_error"] = None
            state["iq_open_assets"] = assets
            state["iq_open_otc"] = cached_otc_open_assets()
        except Exception as error:
            state["iq_catalog_available"] = False
            state["iq_catalog_error"] = f"{type(error).__name__}: {str(error)[:160]}"
        time.sleep(300)


def price_lookup(symbol: str) -> float:
    candles = fetch_candles(symbol, interval="5m", range_="1d", count=1)
    if not candles:
        raise ValueError("preço indisponível")
    return float(candles[-1]["close"])


def price_lookup_at(symbol: str, iso_timestamp: str) -> float:
    """Read the close of the M5 candle at or before a scheduled UTC timestamp."""
    target = datetime.fromisoformat(iso_timestamp).timestamp()
    candles = fetch_candles(symbol, interval="5m", range_="2d", count=600)
    eligible = [candle for candle in candles if candle.get("timestamp") is not None and float(candle["timestamp"]) <= target]
    if not eligible:
        raise ValueError("candle histórica indisponível")
    candle = eligible[-1]
    if target - float(candle["timestamp"]) > 10 * 60:
        raise ValueError("candle histórica atrasada")
    return float(candle["close"])


def settlement_loop() -> None:
    if not BOT_TOKEN:
        return
    while True:
        try:
            state["settlement_last_check"] = datetime.now(timezone.utc).isoformat()
            capture_entry_prices(price_lookup_at)
            settled = settle_pending(price_lookup, price_lookup_at)
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
    """Publish one persistent summary for every 20 finalized results."""
    if not BOT_TOKEN:
        return
    while True:
        try:
            batch = next_result_batch(20)
            if batch and send_message(format_result_batch(batch)):
                mark_result_batch(batch["start"], batch["total"])
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
                    send_signal(create_signal(result), chat_id)
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
        send_message(format_session_summary(session_statistics(1)), chat_id)
    elif text == "/ajuda":
        send_message(
            "NEXUS IA TRADER\n\n"
            "/analisar EUR/JPY — análise M5/M15/H1\n"
            "/sinal EUR/JPY — cria registro PAPER TRADING\n"
            "/resultado ID WIN|LOSS|VOID — fecha simulação\n"
            "/historico — lista simulações\n\n"
            "/stats [ATIVO] — mostra estatísticas gerais ou por ativo\n\n"
            "/ranking — compara os ativos da amostra\n\n"
            "/sessao — resumo da última hora\n\n"
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
    return render_template("dashboard.html")
@app.get("/api/dashboard")
def dashboard_data():
    """Public read-only view of the persistent journal for the web app."""
    signals = recent_signals(100)
    return jsonify({
        "live": [signal for signal in signals if signal.get("outcome") == "PENDENTE"],
        "results": [signal for signal in signals if signal.get("outcome") in {"WIN", "LOSS", "VOID"}],
        "statistics": statistics(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "online",
            "mode": BOT_MODE,
            "telegram_configured": bool(BOT_TOKEN),
            "channel_configured": bool(CHANNEL_ID),
            "paper_database": backend_name(),
            "started_at": state["started_at"],
            "last_update": state["last_update"],
            "last_message": state["last_message"],
            "auto_signals_enabled": AUTO_SIGNALS_ENABLED,
            "auto_signal_min_confidence": AUTO_SIGNAL_MIN_CONFIDENCE,
            "auto_signal_max_daily": AUTO_SIGNAL_MAX_DAILY,
            "auto_otc_only": AUTO_OTC_ONLY,
            "auto_require_full_alignment": AUTO_REQUIRE_FULL_ALIGNMENT,
            "auto_symbols": state["auto_symbols"],
            "auto_asset_modes": available_asset_modes(),
            "auto_sent_today": state["auto_sent_today"],
            "auto_last_scan": state["auto_last_scan"],
            "auto_cycle_started": state["auto_cycle_started"],
            "auto_cycle_completed": state["auto_cycle_completed"],
            "auto_cycle_progress": f"{state['auto_cycle_processed']}/{state['auto_cycle_total']}",
            "auto_current_symbol": state["auto_current_symbol"],
            "iq_catalog_available": state["iq_catalog_available"],
            "iq_catalog_last_refresh": state["iq_catalog_last_refresh"],
            "iq_catalog_error": state["iq_catalog_error"],
            "iq_open_assets": state["iq_open_assets"],
            "iq_open_otc": cached_otc_open_assets(),
            "auto_last_decisions": state["auto_last_decisions"],
            "auto_scan_errors": state["auto_scan_errors"],
            "auto_last_error": state["auto_last_error"],
            "last_settlement": state["last_settlement"],
            "settlement_last_check": state["settlement_last_check"],
            "settled_count": state["settled_count"],
            "settlement_error": state["settlement_error"],
            "history_reset_applied": HISTORY_RESET_APPLIED,
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
            "diagnostics": market_data_diagnostics(),
            "candle_available": bool(candles),
            "candle_fresh": is_fresh(candles, 10 * 60),
            "provider": "IQ Option only",
            "iq_option_configured": market_data_diagnostics().get("iq_option_configured", False),
        })
    except Exception as error:
        return jsonify({
            "status": "error",
            "symbol": symbol,
            "detail": type(error).__name__,
            "diagnostics": market_data_diagnostics(),
            "provider": "IQ Option only",
            "iq_option_configured": market_data_diagnostics().get("iq_option_configured", False),
        }), 503


if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=polling_loop, daemon=True).start()
        threading.Thread(target=settlement_loop, daemon=True).start()
        threading.Thread(target=session_summary_loop, daemon=True).start()
        if AUTO_SIGNALS_ENABLED:
            threading.Thread(target=auto_scan_loop, daemon=True).start()
            if AUTO_INCLUDE_IQ_ASSETS:
                threading.Thread(target=asset_catalog_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
