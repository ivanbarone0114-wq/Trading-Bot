"""Justificación (a favor) y refutación (en contra) de cada operación, para el panel."""
import json

NAMES = {"trend": "Tendencia", "macd": "MACD", "rsi": "RSI", "patterns": "Velas", "news": "Noticias"}


def _resistance(df, n=50):
    return float(df["high"].tail(n).max()) if df is not None and len(df) else None


def explain_entry(sig, row, df, cfg):
    st = cfg["strategy"]
    pro, contra = [], []
    keys = {"trend": "Tendencia", "macd": "MACD", "rsi": "RSI", "patterns": "Velas", "news": "Noticias"}
    for k, v in sorted(sig.components.items(), key=lambda x: -abs(x[1])):
        text = next((r for r in sig.reasons if r.startswith(keys.get(k, k)) or (k == "macd" and "MACD" in r)), None)
        if abs(v) < 0.005:
            continue
        label = text or {"macd": f"Histograma MACD {'positivo' if v > 0 else 'negativo'}",
                         "patterns": "Patrón de velas"}.get(k, NAMES.get(k, k))
        (pro if v > 0 else contra).append(f"{label} ({v:+.2f} al score)")
    if sig.htf == 1:
        pro.append("La temporalidad mayor también es alcista")
    elif sig.htf == -1:
        contra.append("La temporalidad mayor es bajista: la compra va contra la tendencia de fondo")
    atr, price = sig.atr or 0, sig.price
    if atr:
        ext = (price - float(row["ema_fast"])) / atr
        if ext > 2:
            contra.append(f"Precio estirado: {ext:.1f} ATR sobre la EMA rápida, riesgo de retroceso")
        if atr / price > 0.04:
            contra.append(f"Volatilidad alta (ATR {atr / price:.1%} del precio): el stop puede saltar por ruido")
    if 65 < sig.rsi <= st["rsi_overbought"]:
        contra.append(f"RSI {sig.rsi:.0f}: poco margen antes de sobrecompra")
    res = _resistance(df)
    if res and atr and 0 <= (res - price) / atr < 1:
        contra.append(f"Resistencia cercana en {res:,.2f} (a menos de 1 ATR)")
    if res and sig.target and sig.target > res * 1.001:
        contra.append(f"El objetivo ({sig.target:,.2f}) está por encima de la resistencia de 50 velas ({res:,.2f})")
    if sig.news is not None and sig.news < 0:
        contra.append("Las noticias recientes tienen sesgo negativo")
    if sig.score - st["threshold"] < 0.05:
        contra.append(f"Señal justa: score {sig.score:+.2f} apenas sobre el umbral {st['threshold']}")
    resumen = (f"Compra con score {sig.score:+.2f}: {len(pro)} argumentos a favor y {len(contra)} en contra. "
               f"Riesgo definido con stop en {sig.stop:,.2f} y objetivo en {sig.target:,.2f}.")
    return {"resumen": resumen, "pro": pro, "contra": contra, "score": sig.score,
            "rsi": round(sig.rsi, 1), "comp": sig.components}


def explain_exit(why, pos, px, sig, row):
    pro, contra = [], []
    avg = pos.get("avg") or px
    ret = px / avg - 1 if avg else 0
    trend = sig.components.get("trend", 0) if sig else 0
    macd = sig.components.get("macd", 0) if sig else 0
    if why == "stop":
        pro.append(f"Se respetó el stop: la pérdida quedó acotada en {ret:+.1%}")
        if trend > 0:
            contra.append("La tendencia sigue alcista: el stop pudo saltar por ruido; un stop más amplio habría evitado la salida")
        if sig and sig.rsi < 35:
            contra.append(f"Salió con RSI {sig.rsi:.0f}, zona donde suelen darse rebotes")
    elif why == "objetivo":
        pro.append(f"Se alcanzó el objetivo: {ret:+.1%}")
        if trend > 0 and macd > 0:
            contra.append("La tendencia y el MACD siguen a favor: un stop dinámico (trailing) podría haber capturado más")
    else:
        pro.append(f"El score cayó a {sig.score:+.2f}, por debajo del umbral de salida" if sig else "Señal de salida")
        if sig:
            pro += [r for r in sig.reasons if "bajista" in r or "sobrecompra" in r]
        if ret > 0:
            pro.append(f"Aseguró ganancia de {ret:+.1%} antes de que la señal empeore")
        else:
            pro.append(f"Salió antes de tocar el stop, con {ret:+.1%}")
        if sig and sig.rsi < 30:
            contra.append(f"Vendió en sobreventa (RSI {sig.rsi:.0f}): suelen darse rebotes técnicos")
        if sig and sig.htf == 1:
            contra.append("La temporalidad mayor sigue alcista: la salida puede ser prematura")
    resumen = f"Venta por {why} con resultado {ret:+.1%}."
    return {"resumen": resumen, "pro": pro, "contra": contra, "ret": round(ret, 4),
            "score": sig.score if sig else None}


def dumps(d):
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))
