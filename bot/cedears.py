"""CEDEARs: CCL implícito de cada uno y detección de desvíos (posibles arbitrajes) contra el CCL de referencia."""
import statistics
from .ccl import _last, implied_ccl

# Ratios orientativos (CEDEARs por cada acción). VERIFICAR contra la tabla oficial del programa CEDEAR:
# cambian con splits. Si un ratio está mal, el panel lo marca y sugiere el correcto.
DEFAULT_CEDEARS = [
    {"symbol": "AAPL", "ratio": 20}, {"symbol": "MSFT", "ratio": 30}, {"symbol": "GOOGL", "ratio": 58},
    {"symbol": "AMZN", "ratio": 144}, {"symbol": "META", "ratio": 24}, {"symbol": "NVDA", "ratio": 24},
    {"symbol": "TSLA", "ratio": 15}, {"symbol": "KO", "ratio": 5}, {"symbol": "MELI", "ratio": 120},
    {"symbol": "SPY", "ratio": 20}, {"symbol": "QQQ", "ratio": 20},
]


def cedear_list(cfg):
    c = cfg.get("cedears")
    if c is None:
        return []
    return c.get("list") or DEFAULT_CEDEARS


def arbitrage(cfg, cache=None, offline=False):
    """Filas: símbolo, precio ARS, precio USD, ratio, CCL implícito, desvío vs referencia y lectura."""
    cache = cache if cache is not None else {}
    c = cfg.get("cedears") or {}
    thr = float(c.get("alert_pct", 0.03))
    rows = []
    for it in cedear_list(cfg):
        sym, ratio, us = it["symbol"], float(it["ratio"]), it.get("us", it["symbol"])
        try:
            ars, d_ars = _last(cache, sym, "byma", offline)
            usd, d_usd = _last(cache, us, "us", offline)
        except Exception as e:
            print(f"[cedear] {sym}: {e}")
            continue
        rows.append({"symbol": sym, "ars": ars, "usd": usd, "ratio": ratio, "ccl": ars * ratio / usd,
                     "same_day": d_ars == d_usd, "d_ars": str(d_ars), "d_usd": str(d_usd)})
    _, ref = implied_ccl(cfg, cache, offline)
    ref_src = "GGAL/YPF"
    if not ref and rows:
        ref, ref_src = statistics.median(r["ccl"] for r in rows), "mediana CEDEARs"
    for r in rows:
        dev = r["ccl"] / ref - 1 if ref else 0.0
        r["dev"] = dev
        if abs(dev) > 0.25:
            r["read"], r["kind"] = f"Revisar ratio (sugerido ≈ {round(ref * r['usd'] / r['ars'])})", "check"
        elif not r["same_day"]:
            r["read"], r["kind"] = "Precios de días distintos: no comparable", "stale"
        elif dev <= -thr:
            r["read"], r["kind"] = "CEDEAR barato: dólar implícito más bajo que el CCL", "cheap"
        elif dev >= thr:
            r["read"], r["kind"] = "CEDEAR caro: dólar implícito más alto que el CCL", "rich"
        else:
            r["read"], r["kind"] = "En línea con el CCL", "ok"
    return rows, ref, ref_src, thr
