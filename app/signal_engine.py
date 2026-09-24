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

    fast = ema(closes, 9)
    slow = ema(closes, 21)
    trend = ema(closes, 50)
    momentum = rsi(closes)
    volatility_pct, latest_move_pct = volatility_metrics(closes)
    macd_line, macd_signal, macd_histogram = macd(closes)
    lower_band, middle_band, upper_band = bollinger(closes)
    recent = closes[-1]
    score = 50
    reasons = []

    if fast > slow:
        score += 20
        reasons.append("EMA 9 acima da EMA 21")
    elif fast < slow:
        score -= 20
        reasons.append("EMA 9 abaixo da EMA 21")

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
        "bollinger_lower": lower_band,
        "bollinger_middle": middle_band,
        "bollinger_upper": upper_band,
        "volatility_pct": volatility_pct,
        "latest_move_pct": latest_move_pct,
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
    context = analyze(symbol, h1_candles) if h1_candles else None
    trigger = analyze(symbol, m1_candles) if m1_candles else None
    result["h1_decision"] = context["decision"] if context else "indisponível"
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
    result["confluence_ok"] = (
        result["decision"] in ("CALL", "PUT")
        and result["m15_decision"] == result["decision"]
        and confirmation_confidence >= 70
        and result["h1_decision"] == result["decision"]
        and context_confidence >= 65
        and result["m1_confirmation_ok"]
        and volatility_ok
        and trend_momentum_ok
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
