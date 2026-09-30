"""Dólar CCL implícito: precio local (ARS) x ratio / precio del ADR (USD)."""
from .data import fetch_ohlcv

DEFAULT_PAIRS = [
    {"local": "GGAL", "adr": "GGAL", "ratio": 10},  # 1 ADR = 10 acciones locales
    {"local": "YPFD", "adr": "YPF", "ratio": 1},    # 1 ADR = 1 acción local
]


def _last(cache, symbol, market, offline):
    key = symbol + ".BA" if market == "byma" else symbol
    if key in cache:
        return cache[key]
    df = fetch_ohlcv(symbol, market, "1d", 10, offline)
    cache[key] = (float(df["close"].iloc[-1]), df.index[-1].date())
    return cache[key]


def implied_ccl(cfg, cache=None, offline=False):
    """Devuelve (lista de (par, ccl, avisos), promedio o None)."""
    cache = cache if cache is not None else {}
    pairs = cfg.get("ccl", {}).get("pairs", DEFAULT_PAIRS)
    out = []
    for p in pairs:
        try:
            loc, d_loc = _last(cache, p["local"], "byma", offline)
            adr, d_adr = _last(cache, p["adr"], "us", offline)
            note = "" if d_loc == d_adr else f" (fechas distintas: {d_loc:%d/%m} vs {d_adr:%d/%m})"
            out.append((p["local"], loc * p["ratio"] / adr, note))
        except Exception as e:
            print(f"[ccl] {p['local']}: {e}")
    vals = [v for _, v, _ in out]
    return out, (sum(vals) / len(vals) if vals else None)


def ccl_lines(cfg, cache=None, offline=False):
    rows, avg = implied_ccl(cfg, cache, offline)
    if avg is None:
        return []
    lines = ["", "💵 <b>Dólar CCL implícito</b>"]
    lines += [f"Vía {name}: ${v:,.2f}{note}" for name, v, note in rows]
    if len(rows) > 1:
        lines.append(f"Promedio: ${avg:,.2f}")
        spread = (max(v for _, v, _ in rows) / min(v for _, v, _ in rows) - 1)
        if spread > 0.02:
            lines.append(f"⚠️ Diferencia entre papeles {spread:.1%}: posible arbitraje o dato desfasado")
    return lines
