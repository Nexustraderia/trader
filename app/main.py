import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

try:
    from .db import backend_name
    from .iq_data import available_asset_modes, available_signal_assets, cached_otc_open_assets, is_iq_asset_open
    from .market_data import fetch_candles, is_fresh, market_data_diagnostics, market_data_source, normalize_symbol
    from .paper_journal import capture_entry_prices, close_signal, create_signal, format_history, format_ranking, format_result, format_result_batch, format_session_summary, format_signal, format_statistics, get_telegram_file_id, mark_result_batch, mark_result_delivered, next_result_batch, pending_result_deliveries, pending_signal_status, ranking, recent_signals, save_telegram_file_id, session_statistics, settle_pending, statistics
    from .signal_engine import analyze_with_confirmation, format_analysis
except ImportError:
    from db import backend_name
    from iq_data import available_asset_modes, available_signal_assets, cached_otc_open_assets, is_iq_asset_open
    from market_data import fetch_candles, is_fresh, market_data_diagnostics, market_data_source, normalize_symbol
    from paper_journal import capture_entry_prices, close_signal, create_signal, format_history, format_ranking, format_result, format_result_batch, format_session_summary, format_signal, format_statistics, get_telegram_file_id, mark_result_batch, mark_result_delivered, next_result_batch, pending_result_deliveries, pending_signal_status, ranking, recent_signals, save_telegram_file_id, session_statistics, settle_pending, statistics
    from signal_engine import analyze_with_confirmation, format_analysis

load_dotenv()

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
BASE_AUTO_SYMBOLS = tuple(item.strip() for item in os.getenv("AUTO_SYMBOLS", "EUR/USD,EUR/JPY,USD/JPY,GBP/USD,GBP/JPY,AUD/USD,USD/CAD").split(",") if item.strip())
OTC_AUTO_SYMBOLS = tuple(f"{symbol}-OTC" for symbol in BASE_AUTO_SYMBOLS)
AUTO_SYMBOLS = BASE_AUTO_SYMBOLS + (OTC_AUTO_SYMBOLS if os.getenv("AUTO_INCLUDE_OTC", "true").lower() == "true" else ())
RESULT_IMAGE_PATHS = {
    "WIN": os.getenv("WIN_IMAGE_PATH", os.path.join(os.path.dirname(__file__), "assets", "win.png")),
    "LOSS": os.getenv("LOSS_IMAGE_PATH", os.path.join(os.path.dirname(__file__), "assets", "loss.png")),
}
RESULT_STICKER_IDS = {
    "WIN": os.getenv("WIN_STICKER_FILE_ID", "").strip(),
    "LOSS": os.getenv("LOSS_STICKER_FILE_ID", "").strip(),
}
SIGNAL_STICKER_FILE_ID = os.getenv(
    "SIGNAL_STICKER_FILE_ID",
    "CAACAgEAAxkBAAFU1olqtERbheqendjULXdKIX-apGKBRAACUgkAAnDjoEUmIym3kq2dsT0E",
).strip()

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
    "auto_cycle_total": len(AUTO_SYMBOLS),
    "auto_current_symbol": None,
    "auto_symbols": list(AUTO_SYMBOLS),
    "signal_sticker_error": None,
    "auto_last_decisions": {},
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
    """Send the anti-martingale sticker, then the formatted signal."""
    state["signal_sticker_error"] = None
    if BOT_TOKEN and SIGNAL_STICKER_FILE_ID:
        try:
            response = requests.post(
                telegram_url("sendSticker"),
                json={"chat_id": chat_id or CHANNEL_ID, "sticker": SIGNAL_STICKER_FILE_ID},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            state["signal_sticker_error"] = type(error).__name__
            if getattr(error, "response", None) is not None:
                try:
                    detail = error.response.json().get("description", "")
                    state["signal_sticker_error"] = f"{type(error).__name__}: {detail[:140]}"
                except ValueError:
                    pass
    elif not SIGNAL_STICKER_FILE_ID:
        state["signal_sticker_error"] = "sticker_file_id_ausente"
    return send_message(format_signal(signal), chat_id, signal_reply_markup())


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
        try:
            scan_symbols = available_signal_assets()
        except Exception:
            scan_symbols = list(AUTO_SYMBOLS)
        if not scan_symbols:
            scan_symbols = list(AUTO_SYMBOLS)
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
    return """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#080d18"><title>NEXUS I.A TRADER</title>
  <style>
    :root{color-scheme:dark;--bg:#080d18;--panel:#111a2b;--line:#24324a;--muted:#91a0b8;--green:#39d98a;--red:#ff6677;--gold:#f8c65d}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#162443 0,#080d18 45%);color:#f6f8fb;font:15px Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;min-height:100vh;padding-top:66px}
    .promo{position:fixed;z-index:10;top:0;left:0;right:0;background:linear-gradient(90deg,#f1b84b,#ffd873,#f1b84b);color:#17120a;text-align:center;padding:13px 16px;font-size:13px;font-weight:900;letter-spacing:.02em;box-shadow:0 2px 18px #0008}.promo a{color:#17120a;text-decoration:underline;text-underline-offset:3px}.wrap{max-width:920px;margin:auto;padding:28px 16px 48px}.brand{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:24px}.brand h1{font-size:22px;letter-spacing:.04em;margin:0}.brand p{color:var(--muted);margin:7px 0 0}.pulse{display:flex;align-items:center;gap:8px;color:var(--green);font-size:12px}.dot{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 14px var(--green)}
    .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}.stat,.card{background:rgba(17,26,43,.9);border:1px solid var(--line);border-radius:16px}.stat{padding:14px}.stat b{display:block;font-size:21px;margin-top:5px}.stat span{color:var(--muted);font-size:12px}.tabs{display:flex;gap:8px;margin-bottom:14px}.tab{border:1px solid var(--line);background:#0d1524;color:var(--muted);border-radius:10px;padding:11px 16px;cursor:pointer;font-weight:700}.tab.active{background:#1d3c58;color:#fff;border-color:#3b7aa0}.updated{color:var(--muted);font-size:12px;margin:0 0 12px}.list{display:grid;gap:10px}.card{padding:16px;display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center}.symbol{font-weight:800;font-size:17px}.meta{color:var(--muted);font-size:12px;margin-top:6px}.direction,.outcome{font-weight:900;letter-spacing:.05em;text-align:right}.call,.win{color:var(--green)}.put,.loss{color:var(--red)}.pending{color:var(--gold)}.empty{text-align:center;padding:38px 18px;color:var(--muted);border:1px dashed var(--line);border-radius:16px}.footer{color:var(--muted);font-size:12px;text-align:center;margin-top:28px}
    @media(max-width:620px){.wrap{padding-top:20px}.brand{align-items:flex-start}.stats{grid-template-columns:repeat(2,1fr)}.card{padding:14px}.brand h1{font-size:19px}}
  </style>
</head>
<body><div class="promo">NOSSAS ANÁLISES SÃO FEITAS PARA A CORRETORA IQ OPTION · <a href="https://affiliate.iqoption.net/redir/?aff=232843&aff_model=revenue&afftrack=" target="_blank" rel="noopener noreferrer">CLIQUE AQUI E CADASTRE-SE</a></div><main class="wrap">
  <header class="brand"><div><h1>⚡ NEXUS I.A TRADER</h1><p>Análises em tempo real com Inteligência Artificial</p></div><div class="pulse"><i class="dot"></i><span id="online">ONLINE</span></div></header>
  <section class="stats"><div class="stat"><span>Total</span><b id="total">—</b></div><div class="stat"><span>Wins</span><b class="call" id="wins">—</b></div><div class="stat"><span>Losses</span><b class="loss" id="losses">—</b></div><div class="stat"><span>Assertividade</span><b id="accuracy">—</b></div></section>
  <nav class="tabs"><button class="tab active" data-tab="live">Sinais ao vivo</button><button class="tab" data-tab="results">Resultados</button></nav>
  <p class="updated" id="updated">Atualizando...</p><section id="list" class="list"></section>
  <p class="footer">Dados atualizados automaticamente · Sinais para acompanhamento na IQ OPTION</p>
</main>
<script>
  let currentTab='live';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time=v=>v?new Date(v).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}):'—';
  function card(s){const dir=s.direction==='CALL'?'call':'put';const state=s.outcome==='PENDENTE'?'pending':(s.outcome==='WIN'?'win':'loss');const label=s.outcome==='PENDENTE'?'AGUARDANDO':s.outcome;return `<article class="card"><div><div class="symbol">${esc(s.symbol)}</div><div class="meta">Entrada ${time(s.entry_at)} · Expiração ${esc(s.timeframe||'M5')} · ${s.outcome==='PENDENTE'?'Em andamento':'Finalizado'}</div></div><div><div class="direction ${dir}">${esc(s.direction)}</div><div class="outcome ${state}">${label}</div></div></article>`}
  async function load(){try{const r=await fetch('/api/dashboard',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();const st=d.statistics||{};document.querySelector('#total').textContent=st.total??0;document.querySelector('#wins').textContent=st.wins??0;document.querySelector('#losses').textContent=st.losses??0;document.querySelector('#accuracy').textContent=st.accuracy==null?'—':Number(st.accuracy).toFixed(1)+'%';document.querySelector('#online').textContent='ONLINE';const rows=currentTab==='live'?d.live:d.results;document.querySelector('#list').innerHTML=rows.length?rows.map(card).join(''):'<div class="empty">Nenhum registro disponível no momento.</div>';document.querySelector('#updated').textContent='Última atualização: '+new Date().toLocaleTimeString('pt-BR')}catch(e){document.querySelector('#online').textContent='INDISPONÍVEL';document.querySelector('#list').innerHTML='<div class="empty">Não foi possível atualizar os dados agora.</div>'}}
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{currentTab=b.dataset.tab;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===b));load()});load();setInterval(load,15000);
</script></body></html>"""


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
            "auto_symbols": state["auto_symbols"],
            "auto_asset_modes": available_asset_modes(),
            "auto_sent_today": state["auto_sent_today"],
            "auto_last_scan": state["auto_last_scan"],
            "auto_cycle_started": state["auto_cycle_started"],
            "auto_cycle_completed": state["auto_cycle_completed"],
            "auto_cycle_progress": f"{state['auto_cycle_processed']}/{state['auto_cycle_total']}",
            "auto_current_symbol": state["auto_current_symbol"],
            "iq_open_otc": cached_otc_open_assets(),
            "signal_sticker_error": state["signal_sticker_error"],
            "auto_last_decisions": state["auto_last_decisions"],
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
            "diagnostics": market_data_diagnostics(),
            "candle_available": bool(candles),
            "candle_fresh": is_fresh(candles, 10 * 60),
            "twelve_data_configured": bool(os.getenv("TWELVEDATA_API_KEY", "").strip()),
            "iq_option_configured": market_data_diagnostics().get("iq_option_configured", False),
        })
    except Exception as error:
        return jsonify({
            "status": "error",
            "symbol": symbol,
            "detail": type(error).__name__,
            "diagnostics": market_data_diagnostics(),
            "twelve_data_configured": bool(os.getenv("TWELVEDATA_API_KEY", "").strip()),
            "iq_option_configured": market_data_diagnostics().get("iq_option_configured", False),
        }), 503


if __name__ == "__main__":
    if BOT_TOKEN:
        threading.Thread(target=polling_loop, daemon=True).start()
        threading.Thread(target=settlement_loop, daemon=True).start()
        threading.Thread(target=session_summary_loop, daemon=True).start()
        if AUTO_SIGNALS_ENABLED:
            threading.Thread(target=auto_scan_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
