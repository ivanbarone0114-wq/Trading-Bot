"""Informe de análisis en Markdown: rendimiento, operaciones, posiciones, señales y un prompt
listo para pegar en un chat de análisis financiero."""
import csv, os
from datetime import datetime, timedelta

import pandas as pd

from .data import fetch_ohlcv
from .strategy import prepare, trend_of

CUR = {"crypto": "USDT", "us": "USD", "byma": "ARS"}
MKT = {"crypto": "Cripto", "us": "EE.UU.", "byma": "BYMA"}


# ---------- utilidades ----------
def _f(x, d=2):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:,.{d}f}"


def _p(x, d=2):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x * 100:+.{d}f}%"


def _table(headers, rows):
    if not rows:
        return "_Sin datos._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _ret_since(df, days):
    if df is None or df.empty:
        return None
    last_t = df.index[-1]
    past = df[df.index <= last_t - pd.Timedelta(days=days)]
    if past.empty:
        return None
    return float(df["close"].iloc[-1]) / float(past["close"].iloc[-1]) - 1


def _local(ts):
    return datetime.fromisoformat(ts).astimezone()


# ---------- operaciones ----------
def pair_trades(rows):
    """Empareja compras y ventas (FIFO) y devuelve (operaciones cerradas, lotes abiertos)."""
    lots, closed = {}, []
    for r in rows:
        if r["kind"] != "trade" or r["mode"] != "paper":
            continue
        sym, t = r["symbol"], _local(r["time"])
        qty, px = float(r["qty"] or 0), float(r["price"] or 0)
        if r["side"] == "buy":
            lots.setdefault(sym, []).append({"t": t, "qty": qty, "px": px, "market": r["market"], "note": r["note"]})
            continue
        open_l = lots.get(sym, [])
        if qty <= 0:  # ventas viejas registradas sin cantidad: se asume cierre total
            qty = sum(l["qty"] for l in open_l)
        remaining, cost, used, first_t, score = qty, 0.0, 0.0, None, ""
        while remaining > 1e-12 and open_l:
            lot = open_l[0]
            take = min(lot["qty"], remaining)
            cost += take * lot["px"]; used += take; remaining -= take
            first_t = first_t or lot["t"]; score = score or lot["note"]
            lot["qty"] -= take
            if lot["qty"] <= 1e-12:
                open_l.pop(0)
        entry = cost / used if used else None
        pnl = float(r["pnl"]) if r["pnl"] else ((px - entry) * qty if entry else 0.0)
        closed.append({"symbol": sym, "market": r["market"], "t_in": first_t, "t_out": t, "entry": entry,
                       "exit": px, "qty": qty, "pnl": pnl, "ret": pnl / cost if cost else None,
                       "why": r["note"], "score_in": score})
    return closed, lots


def trade_stats(closed):
    if not closed:
        return None
    wins = [c for c in closed if c["pnl"] > 0]
    losses = [c for c in closed if c["pnl"] <= 0]
    rets = [c["ret"] for c in closed if c["ret"] is not None]
    gw, gl = sum(c["pnl"] for c in wins), -sum(c["pnl"] for c in losses)
    days = [(c["t_out"] - c["t_in"]).total_seconds() / 86400 for c in closed if c["t_in"]]
    return {
        "n": len(closed), "win_rate": len(wins) / len(closed),
        "avg_win": sum(c["ret"] for c in wins if c["ret"] is not None) / len(wins) if wins else None,
        "avg_loss": sum(c["ret"] for c in losses if c["ret"] is not None) / len(losses) if losses else None,
        "expectancy": sum(rets) / len(rets) if rets else None,
        "pf": gw / gl if gl > 0 else None,
        "avg_days": sum(days) / len(days) if days else None,
        "best": max(closed, key=lambda c: c["ret"] or -9), "worst": min(closed, key=lambda c: c["ret"] or 9),
        "by_reason": {k: sum(1 for c in closed if c["why"] == k) for k in {c["why"] for c in closed}},
    }


# ---------- historial de patrimonio ----------
def equity_by_market(paper, last_px):
    eq = dict(paper.s["cash"])
    for sym, p in paper.s["positions"].items():
        eq[p["market"]] = eq.get(p["market"], 0.0) + p["qty"] * last_px.get(sym, p["avg"])
    return eq


def save_equity_snapshot(state_dir, eq, ccl=None):
    path = os.path.join(state_dir, "equity.csv")
    today = datetime.now().date().isoformat()
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            rows = [r for r in csv.DictReader(f) if r["date"] != today]
    rows.append({"date": today, "crypto": round(eq.get("crypto", 0), 4), "us": round(eq.get("us", 0), 4),
                 "byma": round(eq.get("byma", 0), 2), "ccl": round(ccl, 2) if ccl else ""})
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, ["date", "crypto", "us", "byma", "ccl"])
        w.writeheader(); w.writerows(rows)


def load_equity(state_dir):
    path = os.path.join(state_dir, "equity.csv")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


# ---------- informe ----------
PROMPT = """## Prompt para el chat de análisis

Copiá desde acá hasta el final y pegalo junto con este informe:

> Actuá como analista cuantitativo de mercados y gestor de riesgo. Te paso el informe de un bot de **paper trading** (dinero simulado) que opera cripto, acciones de EE.UU. y BYMA con una estrategia de confluencia técnica: tendencia (EMA rápida/lenta), MACD, RSI, patrones de velas y noticias, con filtro de temporalidad mayor, stop por ATR y objetivo por relación riesgo/beneficio. Los parámetros están en la sección "Configuración".
>
> Con esos datos:
> 1. **Diagnóstico de rendimiento:** evaluá el resultado total y por mercado contra las referencias del período (SPY, Merval, BTC). Para BYMA, tené en cuenta que los montos están en pesos: si hay datos de CCL en el historial, estimá el rendimiento en dólares.
> 2. **Tablas:** armá tablas de rendimiento por operación, por mercado y por motivo de cierre (stop, objetivo, señal), con porcentajes, y si hay historial de patrimonio, un gráfico de su evolución.
> 3. **Calidad de la estrategia:** tasa de acierto, ganancia y pérdida promedio, expectativa por operación, profit factor y duración. Indicá si los stops saltan demasiado seguido, si las salidas por señal llegan tarde y en qué mercados o tipos de activo funciona mejor o peor.
> 4. **Riesgo:** concentración, exposición por mercado, distancia de las posiciones abiertas a sus stops y escenarios de pérdida.
> 5. **Señales actuales:** qué activos muestran mejor y peor configuración técnica y qué vigilar.
> 6. **Recomendaciones:** ajustes concretos de parámetros (umbral, multiplicador ATR, relación objetivo/stop, pesos, cantidad de posiciones), cada uno con su razón y qué dato lo confirmaría o descartaría.
>
> Reglas: decí explícitamente si la muestra de operaciones es demasiado chica para sacar conclusiones; separá hechos de hipótesis; no inventes datos que no estén en el informe; no des recomendaciones de compra o venta de activos específicos como certeza. Respondé en español rioplatense, directo y con tablas.
"""


def build_report(cfg, paper, journal, analyze_fn, items, days=7, offline=False, ccl_rows=None):
    now = datetime.now()
    since = now - timedelta(days=days)
    with open(journal.path) as f:
        all_rows = sorted(csv.DictReader(f), key=lambda r: r["time"])
    closed_all, open_lots = pair_trades(all_rows)
    closed = [c for c in closed_all if c["t_out"] >= since.astimezone()]

    # señales actuales y precios
    sigs, last_px, failed = [], {}, []
    for it in items:
        try:
            sig, df, _ = analyze_fn(it, cfg, offline)
        except Exception as e:
            failed.append(it["symbol"]); print(f"[informe] {it['symbol']}: {e}")
            continue
        st_m = dict(cfg["strategy"]); st_m.update((cfg.get("strategy_overrides") or {}).get(it["market"]) or {})
        d = prepare(df, st_m).iloc[-1]
        last_px[sig.symbol] = float(df["close"].iloc[-1])
        sigs.append((it["market"], sig, d, _ret_since(df, 30)))

    eq = equity_by_market(paper, last_px)
    cap = cfg["capital"]
    st = cfg["strategy"]; rk = cfg["risk"]

    md = [f"# Informe del bot de trading (paper)",
          f"Generado: {now:%d/%m/%Y %H:%M} (hora Argentina) | Período analizado: últimos {days} días "
          f"({since:%d/%m} al {now:%d/%m})", ""]

    # 1. Resumen
    md += ["## 1. Resumen de rendimiento", ""]
    rows = []
    for m in ("crypto", "us", "byma"):
        unreal = sum((last_px.get(s, p["avg"]) - p["avg"]) * p["qty"] for s, p in paper.s["positions"].items() if p["market"] == m)
        real = sum(c["pnl"] for c in closed_all if c["market"] == m)
        rows.append([MKT[m], CUR[m], _f(cap[m]), _f(eq.get(m, 0)), _p(eq.get(m, 0) / cap[m] - 1 if cap[m] else None),
                     _f(real), _f(unreal), _f(paper.s["cash"].get(m, 0)),
                     f"{1 - paper.s['cash'].get(m, 0) / eq[m]:.1%}" if eq.get(m) else "—"])
    md.append(_table(["Mercado", "Moneda", "Capital inicial", "Patrimonio actual", "Rendimiento total",
                      "PnL realizado", "PnL no realizado", "Efectivo", "% invertido"], rows))
    md.append("_El rendimiento total compara el patrimonio actual con el capital configurado. Si el efectivo se editó a mano, puede no coincidir._\n")

    # Referencias
    bench = []
    for sym, mkt, name in (("SPY", "us", "S&P 500 (SPY)"), ("^MERV", "us", "Merval (ARS)"), ("BTC/USDT", "crypto", "Bitcoin")):
        try:
            df = fetch_ohlcv(sym, mkt, "1d", 60, offline)
            bench.append([name, _p(_ret_since(df, days)), _p(_ret_since(df, 30))])
        except Exception as e:
            print(f"[informe] referencia {sym}: {e}")
    md += ["### Referencias del período", "", _table(["Índice", f"Últimos {days} días", "Últimos 30 días"], bench)]

    # 2. Estadísticas
    md += ["## 2. Estadísticas de operaciones cerradas", ""]
    for label, data in ((f"Últimos {days} días", closed), ("Desde el inicio", closed_all)):
        s = trade_stats(data)
        md.append(f"**{label}:** " + ("sin operaciones cerradas." if not s else
                  f"{s['n']} operaciones | acierto {s['win_rate']:.0%} | ganancia prom. {_p(s['avg_win'])} | "
                  f"pérdida prom. {_p(s['avg_loss'])} | expectativa {_p(s['expectancy'])} | profit factor "
                  f"{_f(s['pf'])} | duración prom. {_f(s['avg_days'], 1)} días | cierres: "
                  + ", ".join(f"{k} {v}" for k, v in s["by_reason"].items())))
        md.append("")

    # 3. Operaciones cerradas
    md += [f"## 3. Operaciones cerradas (últimos {days} días)", ""]
    md.append(_table(["Activo", "Mercado", "Entrada", "Precio entrada", "Salida", "Precio salida", "Días",
                      "Resultado %", "PnL", "Motivo", "Score de entrada"],
                     [[c["symbol"], MKT.get(c["market"], c["market"]), f"{c['t_in']:%d/%m %H:%M}" if c["t_in"] else "—",
                       _f(c["entry"]), f"{c['t_out']:%d/%m %H:%M}", _f(c["exit"]),
                       _f((c["t_out"] - c["t_in"]).total_seconds() / 86400, 1) if c["t_in"] else "—",
                       _p(c["ret"]), _f(c["pnl"]), c["why"], c["score_in"].replace("score ", "")] for c in closed]))

    # 4. Posiciones abiertas
    md += ["## 4. Posiciones abiertas", ""]
    prow = []
    for sym, p in paper.s["positions"].items():
        px = last_px.get(sym, p["avg"])
        lot_t = min((l["t"] for l in open_lots.get(sym, []) if l["qty"] > 1e-12), default=None)
        prow.append([sym, MKT[p["market"]], _f(p["qty"], 4), _f(p["avg"]), _f(px), _p(px / p["avg"] - 1),
                     _f(p.get("stop")), _f(p.get("target")),
                     _p(p["stop"] / px - 1) if p.get("stop") else "—",
                     f"{p['qty'] * px / eq[p['market']]:.1%}" if eq.get(p["market"]) else "—",
                     _f((now.astimezone() - lot_t).total_seconds() / 86400, 1) if lot_t else "—"])
    md.append(_table(["Activo", "Mercado", "Cantidad", "Precio entrada", "Precio actual", "Resultado %",
                      "Stop", "Objetivo", "Distancia al stop", "% del mercado", "Días abierta"], prow))

    # 5. Historial de patrimonio
    hist = load_equity(cfg["state_dir"])
    md += ["## 5. Evolución del patrimonio (cierre diario)", ""]
    md.append(_table(["Fecha", "Cripto (USDT)", "EE.UU. (USD)", "BYMA (ARS)", "CCL"],
                     [[r["date"], r["crypto"], r["us"], r["byma"], r["ccl"] or "—"] for r in hist[-60:]]))

    # 6. Señales
    md += ["## 6. Señales actuales de todos los activos", ""]
    n = {a: sum(1 for _, s, _, _ in sigs if s.action == a) for a in ("BUY", "SELL", "HOLD")}
    md.append(f"Analizados {len(sigs)} activos: {n['BUY']} BUY, {n['SELL']} SELL, {n['HOLD']} HOLD."
              + (f" Sin datos: {', '.join(failed)}." if failed else "") + "\n")
    trend = {1: "alcista", -1: "bajista", 0: "lateral"}
    md.append(_table(["Activo", "Mercado", "Señal", "Score", "Precio", "Var. 30 días", "RSI", "MACD", "Tendencia", "Velas"],
                     [[s.symbol, MKT[m], s.action, f"{s.score:+.2f}", _f(s.price), _p(r30), f"{s.rsi:.0f}",
                       "↑" if d["macd_hist"] > 0 else "↓", trend[trend_of(d)], s.patterns.replace("_", " ") or "—"]
                      for m, s, d, r30 in sorted(sigs, key=lambda x: -x[1].score)]))

    # 7. CCL
    if ccl_rows:
        md += ["## 7. Dólar CCL implícito", "", _table(["Vía", "CCL"], [[n_, _f(v)] for n_, v, _ in ccl_rows])]

    # 8. Configuración
    md += ["## 8. Configuración de la estrategia", "",
           f"- Tendencia: EMA {st['ema_fast']}/{st['ema_slow']} | RSI {st['rsi_period']} ({st['rsi_oversold']}/{st['rsi_overbought']}) | "
           f"MACD {st['macd_fast']}/{st['macd_slow']}/{st['macd_signal']}",
           f"- Umbral de señal: ±{st['threshold']} | Pesos: " + ", ".join(f"{k} {v}" for k, v in st["weights"].items()),
           f"- Stop: {st['atr_stop_mult']} × ATR({st['atr_period']}) | Objetivo: {st['reward_risk']} × distancia al stop",
           f"- Riesgo por operación: {rk['risk_per_trade']:.1%} | Máx. por activo: {rk['max_position_pct']:.0%} | "
           f"Máx. posiciones por mercado: {rk['max_open_positions']} | Pérdida diaria máx.: {rk['max_daily_loss_pct']:.0%} | "
           f"Comisión: {rk['fee']:.2%} | Slippage: {rk['slippage']:.2%}",
           "- Solo posiciones compradas (sin cortos). Ciclos cada 25 min en horario de mercado (lunes a viernes, 10:30 a 18:00).",
           "- Datos: Yahoo Finance (BYMA y EE.UU., con demora; YPFD.BA con escala ×10 incorrecta en Yahoo) y Kraken/Yahoo para cripto.",
           "", "---", "", PROMPT]

    s7 = trade_stats(closed)
    summary = {"eq": eq, "cap": cap, "closed": len(closed), "stats": s7, "open": len(paper.s["positions"])}
    return "\n".join(md), summary
