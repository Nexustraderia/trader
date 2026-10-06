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
IQ_OPTION_AFFILIATE_URL = "https://affiliate.iqoption.net/redir/?aff=232843&aff_model=revenue&afftrack="
EMAIL = os.environ["IQ_OPTION_EMAIL"].strip()
PASSWORD = os.environ["IQ_OPTION_PASSWORD"]
MIN_CONFIDENCE = int(os.getenv("AUTO_SIGNAL_MIN_CONFIDENCE", "85"))
MAX_ASSETS = int(os.getenv("MAX_SCAN_ASSETS", "12"))
OTC_ONLY = os.getenv("OTC_ONLY", "false").lower() == "true"
SESSION_SIZE = int(os.getenv("SESSION_SIZE", "25"))
SIGNAL_TIMEFRAME = os.getenv("SIGNAL_TIMEFRAME", "1m").lower()
EXPIRY_MINUTES = 1 if SIGNAL_TIMEFRAME == "1m" else 5
DISPLAY_TIMEFRAME = "M1" if EXPIRY_MINUTES == 1 else "M5"
PUT_MIN_CONFIDENCE = int(os.getenv("PUT_MIN_CONFIDENCE", "80"))
OTC_FALLBACK_MIN_CONFIDENCE = int(os.getenv("OTC_FALLBACK_MIN_CONFIDENCE", "85"))
OTC_STRONG_TREND_ADX = float(os.getenv("OTC_STRONG_TREND_ADX", "25"))
QUARANTINE_MIN_SAMPLES = int(os.getenv("QUARANTINE_MIN_SAMPLES", "8"))
QUARANTINE_MAX_ACCURACY = float(os.getenv("QUARANTINE_MAX_ACCURACY", "45"))
QUARANTINE_CYCLES = int(os.getenv("QUARANTINE_CYCLES", "20"))
STAKE_PER_SIGNAL = float(os.getenv("SESSION_STAKE", "2.00"))
PAYOUT_PERCENT = float(os.getenv("SESSION_PAYOUT_PERCENT", "90"))
STATE_PATH = Path(os.getenv("SCANNER_STATE_PATH", "runtime_state.json"))
BRASILIA = ZoneInfo("America/Sao_Paulo")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def telegram(text: str, reply_markup: dict | None = None) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHANNEL_ID, "text": text, **({"reply_markup": reply_markup} if reply_markup else {})},
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
    return current + timedelta(minutes=1 if SIGNAL_TIMEFRAME == "1m" else 5 - current.minute % 5)


def recovery_entry_for(item: dict) -> datetime:
    """Return the exact next candle used by the verifier for G1/MG1."""
    original_entry = datetime.fromisoformat(item["entry_at"])
    return original_entry + timedelta(minutes=EXPIRY_MINUTES)


def candle_at_or_before(symbol: str, target: datetime) -> float:
    candles = fetch_iq_candles(symbol, SIGNAL_TIMEFRAME, 600)
    eligible = [c for c in candles if float(c.get("timestamp", 0)) <= target.timestamp()]
    if not eligible:
        raise RuntimeError(f"No {DISPLAY_TIMEFRAME} candle at or before {target.isoformat()}")
    candle = eligible[-1]
    if target.timestamp() - float(candle["timestamp"]) > 10 * 60:
        raise RuntimeError("Historical M5 candle is stale")
    return float(candle["close"])


def candle_at(symbol: str, target: datetime) -> dict:
    """Return the exact IQ Option candle whose interval starts at target."""
    candles = fetch_iq_candles(symbol, SIGNAL_TIMEFRAME, 600)
    exact = [c for c in candles if float(c.get("timestamp", -1)) == target.timestamp()]
    if not exact:
        raise RuntimeError(f"No exact IQ {DISPLAY_TIMEFRAME} candle at {target.isoformat()}")
    return exact[-1]


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"pending": [], "settled": [], "session_results": [], "completed_sessions": 0}
    try:
        data = json.loads(STATE_PATH.read_text())
        return {
            "pending": list(data.get("pending", [])),
            "settled": list(data.get("settled", [])),
            "session_results": list(data.get("session_results", [])),
            "completed_sessions": int(data.get("completed_sessions", 0)),
            "asset_quarantine": dict(data.get("asset_quarantine", {})),
        }
    except (OSError, ValueError, TypeError):
        return {"pending": [], "settled": [], "session_results": [], "completed_sessions": 0, "asset_quarantine": {}}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def update_asset_quarantine(state: dict) -> set[str]:
    """Temporarily skip regular assets with a meaningful, poor direct sample.

    MG1 is intentionally excluded: the filter should measure the quality of the
    original setup, not the recovery attempt. A quarantine lasts a fixed number
    of scanner cycles and is renewed only when a new direct result arrives.
    """
    rows = [*state.get("settled", []), *state.get("session_results", [])]
    stats: dict[str, list[str]] = {}
    for item in rows:
        if int(item.get("martingale_level") or 0) != 0:
            continue
        outcome = item.get("outcome")
        symbol = item.get("symbol")
        if symbol and outcome in {"WIN", "LOSS"}:
            stats.setdefault(symbol, []).append(outcome)

    quarantine = state.setdefault("asset_quarantine", {})
    for symbol, record in list(quarantine.items()):
        if not isinstance(record, dict):
            quarantine[symbol] = {"remaining": 0, "sample_size": 0}
            continue
        record["remaining"] = max(0, int(record.get("remaining", 0)) - 1)

    active: set[str] = set()
    for symbol, outcomes in stats.items():
        sample_size = len(outcomes)
        accuracy = sum(outcome == "WIN" for outcome in outcomes) / sample_size * 100
        record = quarantine.get(symbol, {})
        if int(record.get("remaining", 0)) > 0:
            active.add(symbol)
        elif sample_size >= QUARANTINE_MIN_SAMPLES and accuracy < QUARANTINE_MAX_ACCURACY:
            # Do not immediately re-quarantine the same unchanged sample after
            # the cooldown expires; a new direct result must justify renewal.
            if sample_size > int(record.get("sample_size", 0)):
                quarantine[symbol] = {
                    "remaining": QUARANTINE_CYCLES,
                    "sample_size": sample_size,
                    "accuracy": round(accuracy, 2),
                }
                active.add(symbol)
    return active


def regular_put_quality_ok(result: dict, confidence: int) -> bool:
    """Require stronger directional evidence for regular PUT setups."""
    if result.get("decision") != "PUT":
        return True
    return (
        confidence >= PUT_MIN_CONFIDENCE
        and result.get("m15_confidence", 0) >= 75
        and result.get("adx", 0.0) >= 22
        and result.get("regular_directional_ok", False)
        and result.get("regular_ema_alignment_ok", False)
        and result.get("regular_macd_ok", False)
        and result.get("regular_atr_ok", False)
        and result.get("m15_di_minus", 0.0) > result.get("m15_di_plus", 0.0)
        and result.get("h1_decision") == "PUT"
    )


def otc_quality_fallback_ok(result: dict) -> bool:
    """Allow a high-quality OTC setup when only price-action confirmation fails.

    OTC candles can provide reliable trend/momentum alignment while the zone
    reaction flag remains unavailable or too strict. This fallback still needs
    complete timeframe direction, strong confidence, healthy volatility and at
    least three of the four independent technical quality checks. PUTs retain
    the stricter directional gate above.
    """
    decision = result.get("decision")
    confidence = int(result.get("regular_confidence", 0) or 0)
    common = (
        decision in {"CALL", "PUT"}
        and confidence >= OTC_FALLBACK_MIN_CONFIDENCE
        and result.get("m1_decision") == decision
        and result.get("m15_decision") == decision
        and result.get("h1_decision") in {decision, "AGUARDAR"}
        and result.get("m1_confirmation_ok", False)
        and result.get("volatility_ok", False)
        and result.get("trend_momentum_ok", False)
        and result.get("rsi_entry_ok", False)
        and result.get("adx", 0.0) >= 18
    )
    if not common:
        return False
    if decision == "PUT":
        return (
            result.get("regular_v2_quality_count", 0) >= 3
            and regular_put_quality_ok(result, confidence)
        )
    # Keep OTC CALLs selective as well: a strong ADX cannot replace a missing
    # independent confirmation on M1.
    return (
        result.get("regular_v2_quality_count", 0) >= 3
        and result.get("adx", 0.0) >= OTC_STRONG_TREND_ADX
    )


def format_signal(result: dict, entry_at: datetime, martingale_level: int = 0) -> str:
    local = entry_at.astimezone(BRASILIA)
    return "\n".join([
        "⚡️ NEXUS I.A TRADER ⚡️",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"💱 ATIVO\n{result['symbol']}",
        "",
        f"📊 DIREÇÃO\n{'🟢' if result['decision'] == 'CALL' else '🔴'} {result['decision']}",
        *("🔁 RECUPERAÇÃO MG1" if martingale_level == 1 else "" ,),
        "",
        f"⏰ ENTRADA\n{local.strftime('%H:%M')} (UTC−3 Brasília)",
        f"⌛ EXPIRAÇÃO\n{DISPLAY_TIMEFRAME}",
        "",
        "",
        "Sinais Exclusivos para a IQ OPTION",
        "Até 1 recuperação permitida.",
        "Não tem conta na IQ OPTION?",
        "Clique no botão abaixo e cadastre-se.",
    ])


def format_result(item: dict, outcome: str) -> str:
    local = datetime.fromisoformat(item["entry_at"]).astimezone(BRASILIA)
    level = int(item.get("martingale_level", 0))
    if level == 1 and outcome == "WIN":
        label = "✅ WIN no MG1"
    elif level == 1 and outcome == "LOSS":
        label = "🔴 LOSS após MG1"
    else:
        label = {"WIN": "✅ WIN", "LOSS": "🔴 LOSS", "VOID": "⚪ VOID"}[outcome]
    return "\n".join([
        "⚡️ NEXUS I.A TRADER ⚡️",
        "📊 Resultado do paper trading",
        "",
        f"💱 Ativo: {item['symbol']}",
        f"📍 Direção: {item['direction']}",
        f"⏰ Entrada: {local.strftime('%H:%M')} (UTC−3 Brasília)",
        f"⌛ Expiração: {DISPLAY_TIMEFRAME}",
        "",
        label,
    ])


def format_session_summary(batch: list[dict]) -> str:
    """Format one attractive 20-signal scoreboard for Telegram."""
    batch = [item for item in batch if item.get("outcome") in {"WIN", "LOSS"}]
    direct_wins = sum(1 for item in batch if int(item.get("martingale_level", 0)) == 0 and item.get("outcome") == "WIN")
    mg1_wins = sum(1 for item in batch if int(item.get("martingale_level", 0)) == 1 and item.get("outcome") == "WIN")
    mg1_losses = sum(1 for item in batch if int(item.get("martingale_level", 0)) == 1 and item.get("outcome") == "LOSS")
    result_icons = {"WIN": "💚", "LOSS": "❌", "VOID": "⚪"}
    lines = [
        "💥🤑 PLACAR NEXUS IA 🤑💥",
        "",
        f"📊 Sessão de {len(batch)} sinais encerrada",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for item in batch:
        local = datetime.fromisoformat(item["entry_at"]).astimezone(BRASILIA)
        symbol = item["symbol"].replace("/", "")
        mg_label = "  MG1" if int(item.get("martingale_level", 0)) == 1 else ""
        lines.append(f"{local.strftime('%H:%M')}  {symbol}  {item['direction']}{mg_label}  {result_icons.get(item.get('outcome'), '⚪')}")
    total_wins = direct_wins + mg1_wins
    decided = total_wins + mg1_losses
    accuracy = total_wins / decided * 100 if decided else 0
    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"✅ WIN: {direct_wins}   🔁 WIN MG1: {mg1_wins}",
        f"❌ LOSS MG1: {mg1_losses}",
        f"🎯 Assertividade: {accuracy:.2f}%",
    ])
    return "\n".join(lines)


def publish_completed_sessions(state: dict) -> None:
    """Publish each complete 100-settlement batch exactly once."""
    session_results = state.setdefault("session_results", [])
    while len(session_results) >= SESSION_SIZE:
        batch = session_results[:SESSION_SIZE]
        telegram(format_session_summary(batch))
        del session_results[:SESSION_SIZE]
        state["completed_sessions"] = int(state.get("completed_sessions", 0)) + 1


def settle_pending(state: dict) -> None:
    remaining = []
    for item in state["pending"]:
        expiry = datetime.fromisoformat(item["expires_at"])
        if expiry > now_utc():
            remaining.append(item)
            continue
        try:
            entry_candle = candle_at(item["symbol"], datetime.fromisoformat(item["entry_at"]))
            item["entry_price"] = float(entry_candle["open"])
            # IQ/SIO settlement uses the close of the candle at expiration.
            # For M1, an entry at 06:22 expires at 06:23, so the exit candle
            # must be timestamped 06:23 rather than reusing the entry candle.
            exit_candle = candle_at(item["symbol"], expiry)
            exit_price = float(exit_candle["close"])
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
            level = int(item.get("martingale_level", 0))
            if outcome == "LOSS" and level == 0:
                # SIO's G1 evaluates the candle immediately after the original
                # signal, not the next candle available when settlement runs.
                # Using wall-clock next_entry() after a delayed cycle shifted
                # MG1 several minutes and made our labels disagree.
                recovery_entry = recovery_entry_for(item)
                recovery = {
                    "symbol": item["symbol"],
                    "direction": item["direction"],
                    "score": item.get("score", 0),
                    "confidence": item.get("confidence", 0),
                    "strategy": item.get("strategy", ""),
                    "entry_at": recovery_entry.isoformat(),
                    "expires_at": (recovery_entry + timedelta(minutes=EXPIRY_MINUTES)).isoformat(),
                    "entry_price": None,
                    "martingale_level": 1,
                    "parent_id": item.get("id"),
                    "parent_entry_at": item.get("entry_at"),
                    "parent_outcome": outcome,
                    "recovery_created_at": now_utc().isoformat(),
                }
                print(
                    f"MG1_SCHEDULED {recovery['symbol']} "
                    f"parent={item.get('entry_at')} recovery={recovery_entry.isoformat()}"
                )
                telegram(format_signal({"symbol": recovery["symbol"], "decision": recovery["direction"]}, recovery_entry, 1))
                remaining.append(recovery)
            else:
                if outcome in {"WIN", "LOSS"}:
                    telegram(format_result(item, outcome))
                    state.setdefault("session_results", []).append(item)
            print(f"RESULT {item['symbol']}={outcome}")
        except Exception as error:
            item["settlement_error"] = f"{type(error).__name__}: {str(error)[:160]}"
            remaining.append(item)
            print(f"SETTLEMENT_ERROR {item['symbol']} {item['settlement_error']}")
    state["pending"] = remaining
    state["settled"] = state["settled"][-100:]
    publish_completed_sessions(state)


def main() -> None:
    if not EMAIL or not PASSWORD:
        raise RuntimeError("IQ Option credentials are missing")
    state = load_state()
    state.setdefault("session_results", [])
    state.setdefault("completed_sessions", 0)
    state.setdefault("asset_quarantine", {})
    settle_pending(state)
    quarantined_assets = update_asset_quarantine(state)
    assets = available_signal_assets()
    if not assets:
        raise RuntimeError("IQ Option returned no open candle assets")
    # IQ Option remains the sole source. When OTC_ONLY is disabled, include
    # every asset the IQ catalog confirms as open, including regular pairs.
    if OTC_ONLY:
        assets = [symbol for symbol in assets if symbol.endswith("-OTC")]
    assets = [symbol for symbol in sorted(assets) if symbol.endswith("-OTC") or symbol not in quarantined_assets][:MAX_ASSETS]
    print(f"IQ_OPEN_ASSETS={len(assets)} QUARANTINED={','.join(sorted(quarantined_assets)) or 'none'}")
    entry = next_entry()
    sent = 0
    # Internal one-minute cycles can revisit the same entry minute. Deduplicate
    # against the complete persisted history, not only currently pending items;
    # otherwise a settled signal may be generated again before the next cron.
    signal_keys = {
        (item.get("symbol"), item.get("entry_at"))
        for bucket in (state["pending"], state["settled"], state.get("session_results", []))
        for item in bucket
        if item.get("symbol") and item.get("entry_at")
    }
    # A direct signal at the candle immediately after a pending direct entry
    # can collide with the MG1 that will be created when that entry settles.
    # Reserve that next candle proactively; this mirrors the SIO sequence and
    # prevents a direct + MG1 pair from being published for one asset/minute.
    recovery_reserved_keys = {
        (item.get("symbol"), recovery_entry_for(item).isoformat())
        for item in state["pending"]
        if item.get("symbol")
        and item.get("entry_at")
        and int(item.get("martingale_level") or 0) == 0
    }
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
            is_regular = not symbol.endswith("-OTC")
            asset_min_confidence = 75 if is_regular else MIN_CONFIDENCE
            effective_confidence = result.get("regular_confidence", 0) if is_regular else result.get("confidence", 0)
            # Regular pairs use the hybrid ADX/confluence base. OTC keeps its
            # primary zone-confluence gate, with a controlled technical
            # fallback for strong setups rejected only by price-action detail.
            primary_eligible = (
                bool(result.get("regular_hybrid_confluence_ok"))
                if is_regular
                else bool(result.get("confluence_ok"))
            )
            fallback_eligible = (not is_regular) and otc_quality_fallback_ok(result)
            # When confluence is false, the engine intentionally reports raw
            # confidence=50. A validated OTC fallback must use its technical
            # regular_confidence for the final gate and persisted signal.
            gate_confidence = (
                int(result.get("regular_confidence", 0) or 0)
                if fallback_eligible
                else int(effective_confidence)
            )
            eligible = (primary_eligible or fallback_eligible) and (
                gate_confidence >= asset_min_confidence
                and result.get("m1_decision") == result.get("decision")
                and result.get("m15_decision") == result.get("decision")
                and result.get("h1_decision") in (result.get("decision"), "AGUARDAR")
                and (result.get("decision") != "PUT" or regular_put_quality_ok(result, gate_confidence))
            )
            print(
                f"{symbol}={result.get('decision')} confidence={effective_confidence} "
                f"M1={result.get('m1_decision')} M15={result.get('m15_decision')} H1={result.get('h1_decision')} "
                f"confidence_min={asset_min_confidence} regular_confidence={result.get('regular_confidence', 0)} "
                f"adx={result.get('adx', 0):.1f} di+={result.get('di_plus', 0):.1f} "
                f"di-={result.get('di_minus', 0):.1f} atr={result.get('atr_pct', 0):.4f} "
                f"v2_quality={result.get('regular_v2_quality_count', 0)}/4 "
                f"hybrid={result.get('regular_hybrid_confluence_ok')} "
                f"otc_fallback={fallback_eligible} "
                f"put_quality={regular_put_quality_ok(result, int(effective_confidence))} eligible={eligible}"
            )
            key = (symbol, entry.isoformat())
            if eligible and key not in signal_keys and key not in recovery_reserved_keys:
                item = {
                    "symbol": symbol,
                    "direction": result["decision"],
                    "score": int(result["score"]),
                    # Persist the same confidence that was actually checked
                    # by the eligibility rule; the legacy raw score can be
                    # 50 after a confirmation adjustment and is not the
                    # directional confidence shown in diagnostics.
                    "confidence": gate_confidence,
                    "strategy": (
                        "REGULAR_HYBRID_ADX_V2"
                        if is_regular
                        else ("OTC_ZONE_CONFLUENCE" if primary_eligible else "OTC_HYBRID_FALLBACK_V22")
                    ),
                    "entry_at": entry.isoformat(),
                    "expires_at": (entry + timedelta(minutes=EXPIRY_MINUTES)).isoformat(),
                    # The price is captured from the exact M5 candle at entry,
                    # not from the earlier analysis candle.
                    "entry_price": None,
                    "martingale_level": 0,
                }
                telegram(
                    format_signal(result, entry),
                    {"inline_keyboard": [[{"text": "CADASTRE-SE NA IQ OPTION", "url": IQ_OPTION_AFFILIATE_URL}]]},
                )
                state["pending"].append(item)
                signal_keys.add(key)
                sent += 1
        except Exception as error:
            print(f"{symbol}=ERROR {type(error).__name__}: {str(error)[:160]}")
    save_state(state)
    print(f"SIGNALS_SENT={sent}")
    print(f"PENDING_RESULTS={len(state['pending'])}")


if __name__ == "__main__":
    main()
