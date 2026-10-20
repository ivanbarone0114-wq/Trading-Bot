"""Prueba histórica de Fibonacci en acciones (velas diarias de Yahoo, desde 2015).

Mismas reglas que el bot: impulso alcista entre pivotes, vela que toca la zona 50%-78,6%, cierra alcista y sobre
el 61,8% -> compra en la apertura siguiente. Stop debajo del mínimo del impulso, objetivo en el máximo, cierre
forzado a las N ruedas. Se separa en dos períodos para ver si el resultado se sostiene, y se compara con:
- "deriva": lo que hubiera dado comprar cualquier día y mantener la misma cantidad de ruedas (sin señal);
- "placebo": las mismas reglas con niveles inventados (45%/55%/70%) en vez de 50%/61,8%/78,6%.
Si el placebo da parecido, el 61,8% no aporta nada especial."""
import json
import os

import numpy as np
import pandas as pd

from .indicators import atr
from .markets import MKT

PERIODOS = (("2015-01-01", "2022-12-31"), ("2023-01-01", "2100-01-01"))


def _sim(df, k, min_imp, max_hold, fee, slip, lv_lo=0.5, lv_mid=0.618, lv_hi=0.786):
    o, h, l, c = (df[x].values for x in ("open", "high", "low", "close"))
    a = atr(df).values
    n, idx = len(df), df.index
    lastL = setup = pos = None
    out = []
    for i in range(2 * k + 1, n - 1):
        j = i - k
        if l[j] == l[j - k:j + k + 1].min():
            lastL = (j, l[j])
            if setup and setup["tL"] < j:
                setup = None
        if h[j] == h[j - k:j + k + 1].max() and lastL and lastL[0] < j and h[j] - lastL[1] >= min_imp * a[j]:
            setup = {"L": lastL[1], "H": h[j], "tL": lastL[0], "age": 0}
        if pos:
            e, stp, tg, ti = pos
            if l[i] <= stp:
                x = min(o[i], stp)
            elif h[i] >= tg:
                x = max(o[i], tg)
            elif i - ti >= max_hold:
                x = c[i]
            else:
                continue
            r = (x * (1 - slip) * (1 - fee)) / (e * (1 + fee)) - 1
            out.append((idx[ti], r, i - ti))
            pos = None
            continue
        if not setup:
            continue
        S = setup
        S["age"] += 1
        R = S["H"] - S["L"]
        lv = lambda f: S["H"] - f * R
        if h[i] > S["H"] or l[i] < S["L"] or S["age"] > 4 * max_hold:
            setup = None
            continue
        if lv(lv_hi) <= l[i] <= lv(lv_lo) and c[i] > o[i] and c[i] > lv(lv_mid):
            e = o[i + 1] * (1 + slip)
            stp = S["L"] - 0.2 * a[i]
            if stp < e < S["H"]:
                pos = (e, stp, S["H"], i + 1)
                setup = None
    return out


def _drift(df, hold, fee, slip):
    """Resultado medio de comprar cualquier día y vender `hold` ruedas después (con costos)."""
    c = df["close"].values
    if len(c) <= hold:
        return []
    r = c[hold:] / c[:-hold] * (1 - slip) * (1 - fee) / ((1 + slip) * (1 + fee)) - 1
    return list(zip(df.index[:-hold], r))


def _stats(rets):
    if not rets:
        return {"n": 0}
    r = np.array(rets)
    g, p = r[r > 0].sum(), -r[r <= 0].sum()
    return {"n": int(len(r)), "acierto": float((r > 0).mean()), "pf": float(g / p) if p > 0 else 9.9,
            "medio": float(r.mean())}


def _download(symbols):
    import yfinance as yf
    data = {}
    for i in range(0, len(symbols), 20):
        chunk = symbols[i:i + 20]
        raw = yf.download(chunk, start="2014-06-01", interval="1d", group_by="ticker", auto_adjust=True,
                          progress=False, threads=True)
        for s in chunk:
            try:
                d = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d.rename(columns=lambda x: str(x).lower())[["open", "high", "low", "close"]].dropna()
                if len(d) > 300:
                    data[s] = d
            except Exception:
                pass
    return data


def run(cfg, offline=False):
    p = cfg.get("fibonacci_acciones") or {}
    k, imp, hold = int(p.get("pivote", 3)), float(p.get("impulso_atr", 3.0)), int(p.get("max_velas", 30))
    slip = float(cfg["risk"].get("slippage", 0.0005))
    uni = cfg.get("universe") or {}
    syms = {"us": sorted({w["symbol"] for w in cfg.get("watchlist") or [] if w["market"] == "us"} | set(uni.get("us") or [])),
            "byma": sorted({w["symbol"] for w in cfg.get("watchlist") or [] if w["market"] == "byma"} | set(uni.get("byma") or []))}
    res = {}
    for mkt, lst in syms.items():
        fee = float((cfg.get("fees") or {}).get(mkt, cfg["risk"].get("fee", 0.001)))
        tick = [s + ".BA" if mkt == "byma" else s for s in lst]
        if offline:
            from .data import synthetic_ohlcv
            data = {s: synthetic_ohlcv(n=2500, seed=i) for i, s in enumerate(tick)}
            data = {s: d.set_axis(pd.bdate_range("2015-01-01", periods=len(d)), axis=0) for s, d in data.items()}
        else:
            data = _download(tick)
        fib, plac, base = [], [], []
        for s, d in data.items():
            fib += _sim(d, k, imp, hold, fee, slip)
            plac += _sim(d, k, imp, hold, fee, slip, 0.45, 0.55, 0.70)
        holds = [t[2] for t in fib]
        h_avg = max(1, int(round(np.mean(holds)))) if holds else hold
        for d in data.values():  # misma duración media que las operaciones de Fibonacci
            base += _drift(d, h_avg, fee, slip)
        mk = {"activos": len(data), "periodos": []}
        for a, b in PERIODOS:
            ta, tb = pd.Timestamp(a), pd.Timestamp(b)
            within = lambda t: ta <= (t.tz_localize(None) if t.tzinfo else t) <= tb
            f = _stats([r for t, r, _ in fib if within(t)])
            pl = _stats([r for t, r, _ in plac if within(t)])
            dr = _stats([r for t, r in base if within(t)])
            mk["periodos"].append({"desde": a[:4], "hasta": "hoy" if b.startswith("2100") else b[:4],
                                   "fib": f, "placebo": pl, "deriva": dr})
        mk["ruedas_prom"] = float(np.mean(holds)) if holds else None
        ok = all(pp["fib"].get("n", 0) >= 30 and pp["fib"].get("pf", 0) >= 1.2
                 and pp["fib"].get("medio", -1) > pp["deriva"].get("medio", 0)
                 and pp["fib"].get("medio", -1) > pp["placebo"].get("medio", 0) for pp in mk["periodos"])
        mk["pasa"] = bool(ok)
        res[mkt] = mk
    with open(os.path.join(cfg["state_dir"], "fibtest.json"), "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    return res


def text(res, cfg):
    p = cfg.get("fibonacci_acciones") or {}
    pc = lambda x: "—" if x is None else f"{x * 100:+.2f}%"
    lines = ["📐 <b>Prueba histórica: Fibonacci en acciones</b>",
             f"Velas diarias desde 2015, con comisiones. Cierre forzado a las {p.get('max_velas', 30)} ruedas."]
    for mkt, mk in res.items():
        lines += ["", f"<b>{MKT[mkt]}</b> ({mk['activos']} activos" +
                  (f", {mk['ruedas_prom']:.0f} ruedas por operación en promedio)" if mk.get("ruedas_prom") else ")")]
        for pp in mk["periodos"]:
            f, pl, dr = pp["fib"], pp["placebo"], pp["deriva"]
            if not f.get("n"):
                lines.append(f"{pp['desde']}-{pp['hasta']}: sin operaciones")
                continue
            lines.append(f"{pp['desde']}-{pp['hasta']}: {f['n']} operaciones, acierto {f['acierto']:.0%}, PF {f['pf']:.2f}, "
                         f"{pc(f['medio'])} por operación | sin señal {pc(dr.get('medio'))} | placebo {pc(pl.get('medio'))}")
        lines.append("✅ Se sostiene en los dos períodos y le gana al placebo y a comprar cualquier día." if mk["pasa"] else
                     "⚠️ No se sostiene: en algún período no le gana a comprar cualquier día, al placebo, o tiene PF bajo o pocas operaciones.")
    lines += ["", "PF = ganancias ÷ pérdidas (más de 1 gana). Sin señal = comprar cualquier día y mantener lo mismo. "
              "Placebo = mismas reglas con niveles inventados (45/55/70%). Resultado pasado, no promesa. DYOR."]
    return "\n".join(lines)
