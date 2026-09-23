from app.signal_engine import analyze_with_confirmation, directional_confidence

rising = [{"close": value} for value in range(100, 180)]
falling = [{"close": value} for value in range(180, 100, -1)]

for label, candles in (("CALL", rising), ("PUT", falling)):
    result = analyze_with_confirmation("TEST", candles, candles, candles, candles)
    print(label, {
        "decision": result["decision"],
        "score": result["score"],
        "confidence": result["confidence"],
        "confluence_ok": result["confluence_ok"],
    })

assert directional_confidence("CALL", 80) == 80
assert directional_confidence("PUT", 20) == 80
assert directional_confidence("AGUARDAR", 20) == 50
