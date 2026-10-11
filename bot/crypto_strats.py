"""Dos estrategias de cripto, probadas con velas reales de BTC (2022-2026, comisión 0,1% + slippage 0,05%):

TENDENCIA (crypto_t): compra cuando, en velas diarias CERRADAS, el precio y la EMA20 están sobre la EMA50;
vende cuando se pierde esa condición. Stop de emergencia a 3 ATR diarios. Pocas operaciones, largas.
  2022-2024: +161% (BTC +95%) | 2025-2026: +1,8% (BTC -12%).

DIARIO (crypto_d): en velas de 1 h CERRADAS, con tendencia diaria y de 4 h alcistas, compra cuando el
histograma MACD cruza a positivo y el precio está sobre la EMA50. Stop en el mínimo de 12 h (- 0,2 ATR),
objetivo 2 veces el riesgo, cierre forzado a las 24 h.
  2022-2024: -11% | 2025-2026: -18%. Se corre en paper para comparar con la de tendencia.
"""
import pandas as pd
from .indicators import ema, rsi, macd, atr
from .strategy import Signal

TF = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}


def closed(df, tf, now=None):
    """Descarta la última vela si todavía no cerró."""
    if df.empty:
        return df
    now = now or pd.Timestamp.now(tz="UTC")
    last = df.index[-1]
    if last.tzinfo is None:
        now = now.tz_convert(None)
    return df.iloc[:-1] if last + TF[tf] > now else df


def _resample(df, rule):
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def _sig(label, action, score, price, stop, target, r, a, reasons, bar_time, comp, explain, htf=0):
    s = Signal(label, action, round(float(score), 3), float(price), stop, target, float(r), float(a),
               "", reasons, str(bar_time), comp, htf, None)
    s.explain = explain
    return s


def trend_signal(label, d_full, cfg):
    p = cfg.get("tendencia", {})
    fast, slow, k = p.get("ema_fast", 20), p.get("ema_slow", 50), p.get("stop_atr", 3.0)
    d = closed(d_full, "1d")
    if len(d) < slow + 5:
        raise ValueError(f"pocas velas diarias ({len(d)})")
    c = d["close"]; e1, e2 = ema(c, fast), ema(c, slow); a = atr(d)
    price, ef, es, av = float(c.iloc[-1]), float(e1.iloc[-1]), float(e2.iloc[-1]), float(a.iloc[-1])
    up = price > es and ef > es
    dist = (price / es - 1)
    score = max(-1.0, min(1.0, dist * 8)) if up else -max(0.05, min(1.0, abs(dist) * 8))
    r = float(rsi(c).iloc[-1])
    stop = price - k * av
    pro, contra = [], []
    if up:
        pro += [f"Precio {price:,.2f} sobre la EMA{slow} diaria ({es:,.2f})", f"EMA{fast} ({ef:,.2f}) sobre EMA{slow}: tendencia diaria alcista"]
        if dist > 0.15:
            contra.append(f"Precio {dist:.0%} sobre la EMA{slow}: entrada tardía, más riesgo de corrección")
        if r > 75:
            contra.append(f"RSI diario {r:.0f}: sobrecompra")
        reasons = pro[:]
        action = "BUY"
    else:
        reasons = [f"Sin tendencia diaria alcista (precio {price:,.2f}, EMA{fast} {ef:,.2f}, EMA{slow} {es:,.2f})"]
        action = "SELL"
    explain = {"resumen": (f"Tendencia diaria {'alcista: se compra y se mantiene mientras dure' if up else 'perdida: fuera del mercado'}. "
                           f"Stop de emergencia en {stop:,.2f} (3 ATR diarios); sin objetivo fijo: sale cuando la tendencia se rompe."),
               "pro": pro, "contra": contra + ["Estrategia de baja frecuencia: acierta 25-40% de las veces y gana por pocas operaciones grandes"],
               "score": round(score, 3), "rsi": round(r, 1)}
    comp = {"trend": round(score, 3)}
    return _sig(label, action, score, price, stop, price * 10, r, av, reasons, d.index[-1], comp, explain, 1 if up else -1)


def day_signal(label, h1_full, d_full, cfg):
    p = cfg.get("diario", {})
    rr, max_h = p.get("reward_risk", 2.0), p.get("max_hold_h", 24)
    h1 = closed(h1_full, "1h"); d = closed(d_full, "1d")
    if len(h1) < 210 or len(d) < 55:
        raise ValueError(f"pocas velas (1h={len(h1)}, 1d={len(d)})")
    h4 = closed(_resample(h1_full, "4h"), "4h")
    c = h1["close"]; e50 = ema(c, 50); line, sigl, hist = macd(c); a = atr(h1); r = rsi(c)
    dc = d["close"]; d20, d50 = ema(dc, 20), ema(dc, 50)
    c4 = h4["close"]; f20, f50 = ema(c4, 20), ema(c4, 50)
    price, av = float(c.iloc[-1]), float(a.iloc[-1])
    conds = [
        ("Tendencia diaria alcista (precio y EMA20 sobre EMA50)", dc.iloc[-1] > d50.iloc[-1] and d20.iloc[-1] > d50.iloc[-1]),
        ("Tendencia de 4 h alcista", f20.iloc[-1] > f50.iloc[-1] and c4.iloc[-1] > f50.iloc[-1]),
        ("Histograma MACD de 1 h cruzó a positivo en la última vela", hist.iloc[-1] > 0 >= hist.iloc[-2]),
        ("Precio sobre la EMA50 de 1 h", price > e50.iloc[-1]),
        ("Volatilidad normal (ATR entre 0,2% y 2% del precio)", 0.002 <= av / price <= 0.02),
    ]
    met = sum(ok for _, ok in conds)
    low12 = float(h1["low"].tail(12).min())
    stop = min(low12 - 0.2 * av, price - 0.5 * av)
    target = price + rr * (price - stop)
    action = "BUY" if met == len(conds) else "HOLD"
    score = round(met / len(conds) * (1 if conds[0][1] else 0.5), 3)
    reasons = [n for n, ok in conds if ok] or ["Ninguna condición de entrada cumplida"]
    move = (target / price - 1)
    rng = float(((d["high"] - d["low"]) / d["close"]).tail(14).mean())
    contra = [f"Falta: {n}" for n, ok in conds if not ok]
    if action == "BUY":
        if move > 0.6 * rng:
            contra.append(f"El objetivo (+{move:.1%}) supera el 60% del rango diario promedio ({rng:.1%}): puede no alcanzarse en 24 h")
        if float(r.iloc[-1]) > 70:
            contra.append(f"RSI de 1 h {float(r.iloc[-1]):.0f}: sobrecompra de corto plazo")
        contra.append("En la prueba con datos reales esta estrategia perdió: las comisiones superan la ventaja de corto plazo")
    explain = {"resumen": (f"Trading diario: {met} de {len(conds)} condiciones. Stop {stop:,.2f}, objetivo {target:,.2f} "
                           f"(+{move:.1%}), cierre forzado a las {max_h} h."),
               "pro": [n for n, ok in conds if ok], "contra": contra, "score": score, "rsi": round(float(r.iloc[-1]), 1)}
    comp = {"trend": round(0.4 * conds[0][1] + 0.2 * conds[1][1], 3), "macd": round(0.2 * conds[2][1], 3)}
    return _sig(label, action, score, price, stop, target, float(r.iloc[-1]), av, reasons, h1.index[-1], comp, explain,
                1 if conds[0][1] else -1)
