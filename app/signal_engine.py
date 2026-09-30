from datetime import datetime, timezone


def ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1]
    multiplier = 2 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for previous, current in zip(values[-period - 1:-1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0 if average_gain else 50.0
    return 100 - (100 / (1 + average_gain / average_loss))


def volatility_metrics(values: list[float], period: int = 14) -> tuple[float, float]:
    """Return average absolute move and latest move as percentages."""
    if len(values) < 2 or values[-1] == 0:
        return 0.0, 0.0
    changes = [abs(current - previous) / abs(previous) * 100 for previous, current in zip(values[-period - 1:], values[-period:]) if previous]
    latest = abs(values[-1] - values[-2]) / abs(values[-2]) * 100 if values[-2] else 0.0
    return (sum(changes) / len(changes) if changes else 0.0), latest


def support_resistance_position(values: list[float], period: int = 20) -> float:
    """Return the latest close's position inside the recent IQ candle range."""
    window = values[-period:] if len(values) >= period else values
    low, high = min(window), max(window)
    span = high - low
    return (values[-1] - low) / span if span else 0.5


def support_resistance_zones(candles: list[dict], lookback: int = 40) -> dict:
    """Find nearby swing zones and the latest candle's rejection context.

    OTC entries should be based on a reaction at a zone, not simply on the
    close being high or low inside a recent range. The function uses only the
    supplied IQ Option candles and remains deterministic for paper testing.
    """
    usable = candles[-lookback:]
    if not usable or not all("high" in c and "low" in c for c in usable):
        return {"available": False, "near_support": False, "near_resistance": False,
                "bullish_rejection": False, "bearish_rejection": False,
                "support_level": None, "resistance_level": None}
    highs = [float(c["high"]) for c in usable]
    lows = [float(c["low"]) for c in usable]
    closes = [float(c["close"]) for c in usable]
    ranges = [max(0.0, h - l) for h, l in zip(highs, lows)]
    avg_range = sum(ranges[-14:]) / max(1, len(ranges[-14:]))
    # A zone is an area; an overly narrow tolerance was blocking every setup
    # when the last IQ candle stopped just short of the swing price.
    tolerance = max(avg_range * 0.50, abs(closes[-1]) * 0.00005)
    swing_lows = [lows[i] for i in range(2, len(lows) - 2)
                  if lows[i] <= min(lows[i - 2:i]) and lows[i] <= min(lows[i + 1:i + 3])]
    swing_highs = [highs[i] for i in range(2, len(highs) - 2)
                   if highs[i] >= max(highs[i - 2:i]) and highs[i] >= max(highs[i + 1:i + 3])]
    close = closes[-1]
    support = max((level for level in swing_lows if level <= close + tolerance), default=min(lows))
    resistance = min((level for level in swing_highs if level >= close - tolerance), default=max(highs))
    candle = usable[-1]
    open_price = float(candle.get("open", close))
    high = float(candle["high"])
    low = float(candle["low"])
    body = abs(close - open_price)
    lower_wick = max(0.0, min(open_price, close) - low)
    upper_wick = max(0.0, high - max(open_price, close))
    near_support = abs(close - support) <= tolerance or abs(low - support) <= tolerance
    near_resistance = abs(close - resistance) <= tolerance or abs(high - resistance) <= tolerance
    bullish_rejection = near_support and close > open_price and lower_wick >= max(body * 1.2, tolerance * 0.25)
    bearish_rejection = near_resistance and close < open_price and upper_wick >= max(body * 1.2, tolerance * 0.25)
    bullish_reaction = near_support and close > open_price and body >= avg_range * 0.25
    bearish_reaction = near_resistance and close < open_price and body >= avg_range * 0.25
    return {
        "available": True,
        "support_level": support,
        "resistance_level": resistance,
        "support_touches": sum(abs(level - support) <= tolerance for level in swing_lows),
        "resistance_touches": sum(abs(level - resistance) <= tolerance for level in swing_highs),
        "near_support": near_support,
        "near_resistance": near_resistance,
        "bullish_rejection": bullish_rejection,
        "bearish_rejection": bearish_rejection,
        "bullish_reaction": bullish_reaction,
        "bearish_reaction": bearish_reaction,
    }


def macd(values: list[float]) -> tuple[float, float, float]:
    fast = ema(values, 12)
    slow = ema(values, 26)
    line = fast - slow
    history = []
    for index in range(max(26, len(values) - 35), len(values) + 1):
        history.append(ema(values[:index], 12) - ema(values[:index], 26))
    signal = ema(history, 9) if history else line
    return line, signal, line - signal


def bollinger(values: list[float], period: int = 20) -> tuple[float, float, float]:
    window = values[-period:] if len(values) >= period else values
    middle = sum(window) / len(window)
    variance = sum((value - middle) ** 2 for value in window) / len(window)
    deviation = variance ** 0.5
    return middle - 2 * deviation, middle, middle + 2 * deviation


def adx(candles: list[dict], period: int = 14) -> float:
    """Calculate a compact ADX from the supplied IQ candles."""
    return directional_movement(candles, period)[0]


def directional_movement(candles: list[dict], period: int = 14) -> tuple[float, float, float]:
    """Return ADX, +DI and -DI using only the supplied IQ candles."""
    if len(candles) < period + 2 or not all("high" in c and "low" in c for c in candles[-(period + 2):]):
        return 0.0, 0.0, 0.0
    rows = candles[-(period + 1):]
    trs, plus_dm, minus_dm = [], [], []
    for previous, current in zip(rows, rows[1:]):
        high, low = float(current["high"]), float(current["low"])
        prev_high, prev_low = float(previous["high"]), float(previous["low"])
        prev_close = float(previous["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        up, down = high - prev_high, prev_low - low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr = sum(trs) / len(trs)
    if atr <= 0:
        return 0.0, 0.0, 0.0
    plus_di = 100 * (sum(plus_dm) / len(plus_dm)) / atr
    minus_di = 100 * (sum(minus_dm) / len(minus_dm)) / atr
    denominator = plus_di + minus_di
    value = 100 * abs(plus_di - minus_di) / denominator if denominator else 0.0
    return value, plus_di, minus_di


def atr_percent(candles: list[dict], period: int = 14) -> float:
    """Return average true range as a percentage of the latest close."""
    if len(candles) < 2 or not all("high" in c and "low" in c for c in candles[-(period + 1):]):
        return 0.0
    rows = candles[-(period + 1):]
    ranges = []
    for previous, current in zip(rows, rows[1:]):
        high, low = float(current["high"]), float(current["low"])
        previous_close = float(previous["close"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    close = abs(float(rows[-1]["close"]))
    return (sum(ranges) / len(ranges)) / close * 100 if close else 0.0


def directional_confidence(decision: str, score: int | float) -> int:
    """Convert the legacy directional score into confidence for either side.

    The original score is intentionally asymmetric: CALL is high (e.g. 80),
    while PUT is low (e.g. 20). Comparing both directly to an entry threshold
    accidentally made automatic PUT signals impossible.
    """
    score = max(0, min(100, int(round(score))))
    if decision == "CALL":
        return score
    if decision == "PUT":
        return 100 - score
    return 50


def _set_confidence(result: dict) -> None:
    result["confidence"] = directional_confidence(result.get("decision", "AGUARDAR"), result.get("score", 50))


def analyze(symbol: str, candles: list[dict]) -> dict:
    closes = [float(candle["close"]) for candle in candles]
    if len(closes) < 20:
        return {"symbol": symbol, "decision": "AGUARDAR", "score": 0, "confidence": 50, "reason": "Dados insuficientes para análise."}

    fast = ema(closes, 20)
    slow = ema(closes, 50)
    trend = ema(closes, 50)
    momentum = rsi(closes)
    volatility_pct, latest_move_pct = volatility_metrics(closes)
    range_position = support_resistance_position(closes)
    macd_line, macd_signal, macd_histogram = macd(closes)
    lower_band, middle_band, upper_band = bollinger(closes)
    trend_strength, di_plus, di_minus = directional_movement(candles)
    atr_pct = atr_percent(candles)
    zones = support_resistance_zones(candles)
    recent = closes[-1]
    score = 50
    reasons = []

    if fast > slow:
        score += 20
        reasons.append("EMA 20 acima da EMA 50")
    elif fast < slow:
        score -= 20
        reasons.append("EMA 20 abaixo da EMA 50")

    if recent > trend:
        score += 10
        reasons.append("Preço acima da EMA 50")
    elif recent < trend:
        score -= 10
        reasons.append("Preço abaixo da EMA 50")

    if 52 <= momentum <= 68:
        score += 15
        reasons.append(f"RSI favorável ({momentum:.1f})")
    elif 32 <= momentum <= 48:
        score -= 15
        reasons.append(f"RSI pressionado ({momentum:.1f})")
    elif momentum > 70 or momentum < 30:
        reasons.append(f"RSI extremo ({momentum:.1f}); risco de entrada atrasada")

    if macd_histogram > 0:
        score += 10
        reasons.append("MACD com momentum positivo")
    elif macd_histogram < 0:
        score -= 10
        reasons.append("MACD com momentum negativo")

    recent_change = (closes[-1] / closes[-6] - 1) * 100
    if recent_change > 0:
        score += 10
        reasons.append(f"Movimento recente positivo ({recent_change:.2f}%)")
    elif recent_change < 0:
        score -= 10
        reasons.append(f"Movimento recente negativo ({recent_change:.2f}%)")

    score = max(0, min(100, score))
    if score >= 70:
        decision = "CALL"
    elif score <= 30:
        decision = "PUT"
    else:
        decision = "AGUARDAR"

    result = {
        "symbol": symbol,
        "decision": decision,
        "score": score,
        "price": recent,
        "rsi": momentum,
        "ema_fast": fast,
        "ema_slow": slow,
        "ema_trend": trend,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "adx": trend_strength,
        "di_plus": di_plus,
        "di_minus": di_minus,
        "atr_pct": atr_pct,
        "ema20": fast,
        "ema50": slow,
        "bollinger_lower": lower_band,
        "bollinger_middle": middle_band,
        "bollinger_upper": upper_band,
        "volatility_pct": volatility_pct,
        "latest_move_pct": latest_move_pct,
        "range_position": range_position,
        **zones,
        "reasons": reasons,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source": "market data provider",
    }
    _set_confidence(result)
    return result


def analyze_with_confirmation(
    symbol: str,
    m5_candles: list[dict],
    m15_candles: list[dict],
    h1_candles: list[dict] | None = None,
    m1_candles: list[dict] | None = None,
) -> dict:
    result = analyze(symbol, m5_candles)
    confirmation_bonus = 0
    confirmation = analyze(symbol, m15_candles)
    result["m15_decision"] = confirmation["decision"]
    result["m15_score"] = confirmation["score"]
    result["m15_adx"] = confirmation.get("adx", 0.0)
    result["m15_di_plus"] = confirmation.get("di_plus", 0.0)
    result["m15_di_minus"] = confirmation.get("di_minus", 0.0)
    result["m15_ema20"] = confirmation.get("ema20", 0.0)
    result["m15_ema50"] = confirmation.get("ema50", 0.0)
    context = analyze(symbol, h1_candles) if h1_candles else None
    trigger = analyze(symbol, m1_candles) if m1_candles else None
    result["h1_decision"] = context["decision"] if context else "indisponível"
    result["h1_adx"] = context.get("adx", 0.0) if context else 0.0
    result["m1_decision"] = trigger["decision"] if trigger else "indisponível"
    result["m1_confirmation_ok"] = True
    volatility_ok = result.get("volatility_pct", 0.0) >= 0.003 and result.get("latest_move_pct", 0.0) <= 1.00
    result["volatility_ok"] = volatility_ok
    if not volatility_ok:
        result["decision"] = "AGUARDAR"
        result["score"] = min(result["score"], 40)
        result["confidence"] = 50
        if result.get("volatility_pct", 0.0) < 0.003:
            result["reasons"].append("Volatilidade insuficiente; mercado possivelmente lateralizado")
        if result.get("latest_move_pct", 0.0) > 1.00:
            result["reasons"].append("Último movimento muito amplo; risco de entrada após impulso")

    if result["decision"] in ("CALL", "PUT"):
        if result["decision"] == confirmation["decision"]:
            result["score"] = min(100, result["score"] + 15)
            confirmation_bonus += 10
            result["reasons"].append(f"Confirmação M15 alinhada ({confirmation['decision']})")
        else:
            result["score"] = max(0, result["score"] - 20)
            result["decision"] = "AGUARDAR"
            result["reasons"].append(f"Conflito com M15 ({confirmation['decision']}); sinal bloqueado")
    if context and result["decision"] in ("CALL", "PUT") and context["decision"] not in (result["decision"], "AGUARDAR"):
        result["score"] = max(0, result["score"] - 15)
        result["decision"] = "AGUARDAR"
        result["reasons"].append(f"Conflito com contexto H1 ({context['decision']}); sinal bloqueado")
    elif context and result["decision"] in ("CALL", "PUT") and context["decision"] == result["decision"]:
        result["score"] = min(100, result["score"] + 10)
        confirmation_bonus += 10
        result["reasons"].append(f"Contexto H1 alinhado ({context['decision']})")
    if trigger and result["decision"] in ("CALL", "PUT"):
        if trigger["decision"] == result["decision"]:
            result["score"] = min(100, result["score"] + 5)
            confirmation_bonus += 5
            result["reasons"].append(f"Gatilho M1 alinhado ({trigger['decision']})")
        elif trigger["decision"] in ("CALL", "PUT") and trigger["decision"] != result["decision"]:
            result["m1_confirmation_ok"] = False
            result["score"] = max(0, result["score"] - 15)
            result["decision"] = "AGUARDAR"
            result["reasons"].append(f"Conflito com gatilho M1 ({trigger['decision']}); entrada bloqueada")
    confirmation_confidence = directional_confidence(confirmation["decision"], confirmation["score"])
    result["m15_confidence"] = confirmation_confidence
    context_confidence = directional_confidence(context["decision"], context["score"]) if context else 50
    result["h1_confidence"] = context_confidence
    rsi_extreme = result.get("rsi", 50) >= 70 or result.get("rsi", 50) <= 30
    result["rsi_entry_ok"] = not rsi_extreme
    if rsi_extreme:
        result["reasons"].append("RSI extremo; entrada bloqueada para evitar atraso")
    trend_momentum_ok = (
        (result["decision"] == "CALL" and result["price"] >= result["ema_trend"] and result["macd_histogram"] >= 0)
        or (result["decision"] == "PUT" and result["price"] <= result["ema_trend"] and result["macd_histogram"] <= 0)
    )
    result["trend_momentum_ok"] = trend_momentum_ok
    result["regular_directional_ok"] = (
        (result["decision"] == "CALL" and result.get("di_plus", 0.0) > result.get("di_minus", 0.0))
        or (result["decision"] == "PUT" and result.get("di_minus", 0.0) > result.get("di_plus", 0.0))
    )
    result["regular_ema_alignment_ok"] = (
        (result["decision"] == "CALL" and result.get("ema20", 0.0) > result.get("ema50", 0.0)
         and result.get("m15_ema20", 0.0) > result.get("m15_ema50", 0.0))
        or (result["decision"] == "PUT" and result.get("ema20", 0.0) < result.get("ema50", 0.0)
            and result.get("m15_ema20", 0.0) < result.get("m15_ema50", 0.0))
    )
    result["regular_macd_ok"] = (
        (result["decision"] == "CALL" and result.get("macd_histogram", 0.0) > 0)
        or (result["decision"] == "PUT" and result.get("macd_histogram", 0.0) < 0)
    )
    result["regular_atr_ok"] = result.get("atr_pct", 0.0) >= 0.003
    result["regular_confidence"] = directional_confidence(result["decision"], result["score"])
    regular_quality_flags = (
        result["regular_directional_ok"],
        result["regular_ema_alignment_ok"],
        result["regular_macd_ok"],
        result["regular_atr_ok"],
    )
    result["regular_v2_quality_count"] = sum(bool(flag) for flag in regular_quality_flags)
    if result.get("zones_available", result.get("available", False)):
        result["price_action_ok"] = (
            (result["decision"] == "CALL" and (result.get("bullish_rejection", False) or result.get("bullish_reaction", False)))
            or (result["decision"] == "PUT" and (result.get("bearish_rejection", False) or result.get("bearish_reaction", False)))
        )
    else:
        # Keep synthetic close-only unit fixtures compatible. Real IQ Option
        # candles include OHLC and therefore use the strict zone rule above.
        result["price_action_ok"] = (
            (result["decision"] == "CALL" and result["range_position"] >= 0.55)
            or (result["decision"] == "PUT" and result["range_position"] <= 0.45)
        )
    result["confluence_ok"] = (
        result["decision"] in ("CALL", "PUT")
        and result["m15_decision"] == result["decision"]
        and confirmation_confidence >= 70
        # H1 is a context filter: neutral context is acceptable, while an
        # opposite directional context remains a hard block.
        and result["h1_decision"] in (result["decision"], "AGUARDAR")
        and (result["h1_decision"] == "AGUARDAR" or context_confidence >= 65)
        and result["m1_confirmation_ok"]
        and volatility_ok
        and trend_momentum_ok
        and result["price_action_ok"]
    )
    result["regular_trend_confluence_ok"] = (
        result["decision"] in ("CALL", "PUT")
        and result["m15_decision"] == result["decision"]
        and result["h1_decision"] in (result["decision"], "AGUARDAR")
        and result["m1_confirmation_ok"]
        and result["volatility_ok"]
        and result["trend_momentum_ok"]
        and result["rsi_entry_ok"]
        and result.get("adx", 0.0) >= 25
        and result["regular_directional_ok"]
        and result["regular_ema_alignment_ok"]
        and result["regular_macd_ok"]
        and result["regular_atr_ok"]
        and result.get("regular_confidence", 0) >= 75
    )
    # Hybrid gate: preserve the historically stronger ADX/confluence base,
    # while requiring at least two independent V2 quality checks. This avoids
    # the old V2 all-or-nothing gate that reduced the sample excessively.
    result["regular_hybrid_confluence_ok"] = (
        result["decision"] in ("CALL", "PUT")
        and result["confluence_ok"]
        and result.get("adx", 0.0) >= 18
        and result["rsi_entry_ok"]
        and result["regular_v2_quality_count"] >= 2
        and result.get("regular_confidence", 0) >= 75
    )
    if not result["confluence_ok"]:
        result["reasons"].append("Confluência completa M5/M15/H1 não confirmada")
    if result["confluence_ok"]:
        # Confidence must describe the final direction and final score after
        # all M15/H1/M1 adjustments; do not reuse the pre-confirmation score.
        result["confidence"] = min(95, directional_confidence(result["decision"], result["score"]) + 5)
    else:
        result["confidence"] = 50
    return result


def format_analysis(result: dict) -> str:
    lines = [
        "NEXUS IA TRADER — ANÁLISE TESTE",
        "",
        f"Ativo: {result['symbol']}",
        f"Direção: {result['decision']}",
        "Período: M5",
        f"Score técnico: {result['score']}/100",
        f"Confiança direcional: {result.get('confidence', 50)}/100",
        f"Confirmação M15: {result.get('m15_decision', 'indisponível')}",
        f"Contexto H1: {result.get('h1_decision', 'indisponível')}",
        f"Gatilho M1: {result.get('m1_decision', 'indisponível')}",
        f"Confluência completa: {'SIM' if result.get('confluence_ok') else 'NÃO'}",
        f"Volatilidade: {'OK' if result.get('volatility_ok') else 'BLOQUEADA'}",
    ]
    if "price" in result:
        lines.extend([f"Preço de referência: {result['price']}", f"RSI: {result['rsi']:.1f}"])
    lines.append("")
    lines.append("Motivos:")
    lines.extend(f"• {reason}" for reason in result.get("reasons", []))
    lines.extend(["", "Modo TESTE — não é ordem nem garantia de resultado.", f"Fonte: {result.get('source', 'indisponível')}"])
    return "\n".join(lines)
