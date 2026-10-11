"""Noticias de subas y bajas de acciones (EE.UU. y BYMA): alertas por movimientos grandes y resúmenes con titulares."""
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo

from .news import news_sentiment
from .notifier import notify
from .cedears import cedear_list

AR = ZoneInfo("America/Argentina/Buenos_Aires")


def _cfg(cfg):
    n = cfg.get("news") or {}
    return {"alert_pct": float(n.get("move_alert_pct", 0.05)), "top": int(n.get("movers_top", 5)),
            "mediodia": n.get("digest_midday", "13:00"), "cierre": n.get("digest_close", "18:15")}


def _state(cfg):
    path = os.path.join(cfg["state_dir"], "news_sent.json")
    try:
        with open(path) as f:
            return path, json.load(f)
    except Exception:
        return path, {}


def changes(cfg, results):
    """[(item, sig, variación del día)] para acciones de EE.UU. y BYMA (sin repetir CEDEARs)."""
    ced = {c["symbol"] for c in cedear_list(cfg)}
    out = []
    for item, sig, df in results or []:
        m = item["market"]
        if m not in ("us", "byma") or (m == "byma" and item["symbol"] in ced) or len(df) < 2:
            continue
        c = df["close"]
        prev = float(c.iloc[-2]); last = float(c.iloc[-1])
        if prev > 0:
            out.append((item, sig, last / prev - 1))
    return out


def headline(item, offline=False):
    if offline:
        return ""
    kw = item.get("keywords") or [f"{item['symbol']} acciones" if item["market"] == "byma" else f"{item['symbol']} stock"]
    _, titles = news_sentiment(kw, 5)
    return titles[0][:140] if titles else ""


def _line(item, sig, chg, offline):
    h = headline(item, offline)
    cur = "ARS" if item["market"] == "byma" else "USD"
    return f"{'🟢' if chg >= 0 else '🔴'} <b>{sig.symbol}</b> {chg:+.1%} | {sig.price:,.2f} {cur}" + (f"\n   📰 {h}" if h else "")


def digest_lines(cfg, results, offline=False, top=None):
    ch = changes(cfg, results)
    if not ch:
        return []
    top = top or _cfg(cfg)["top"]
    ch.sort(key=lambda x: -x[2])
    ups = [x for x in ch if x[2] > 0][:top]
    downs = [x for x in sorted(ch, key=lambda x: x[2]) if x[2] < 0][:top]
    out = ["", "📈 <b>Subas del día</b>"] + ([_line(*x, offline) for x in ups] or ["Ninguna"])
    out += ["", "📉 <b>Bajas del día</b>"] + ([_line(*x, offline) for x in downs] or ["Ninguna"])
    return out


def send_digest(cfg, results, slot, offline=False):
    lines = digest_lines(cfg, results, offline)
    titles = {"mediodia": "a media rueda", "cierre": "al cierre", "pedido": "ahora"}
    if not lines:
        notify("No hay datos de acciones disponibles en este momento.")
        return
    notify(f"🗞️ <b>Acciones: subas y bajas {titles.get(slot, '')} ({datetime.now(AR):%d/%m %H:%M})</b>"
           + "\n".join(lines) + "\nPara comprar, verificá precio y noticias en Bull Market. No es consejo financiero.")


def maybe_digest(cfg, results, slot, offline=False, scan=None):
    """Envía el resumen de mediodía o de cierre una vez por día hábil, en el primer ciclo después del horario."""
    now = datetime.now(AR)
    if now.weekday() >= 5:
        return
    hh, mm = map(int, _cfg(cfg)[slot].split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return
    if slot == "mediodia" and now.hour >= 17:
        return  # si se pasó el mediodía, queda para el de cierre
    path, st = _state(cfg)
    key = f"{now:%Y-%m-%d}|{slot}"
    if st.get(key):
        return
    if results is None and scan:
        results = scan()
    send_digest(cfg, results, slot, offline)
    st[key] = True
    st = {k: v for k, v in st.items() if k[:7] == f"{now:%Y-%m}"}  # solo el mes en curso
    with open(path, "w") as f:
        json.dump(st, f)


def big_move_alerts(cfg, results, offline=False):
    """Aviso inmediato cuando una acción se mueve más que el umbral en el día (una vez por día y por acción)."""
    thr = _cfg(cfg)["alert_pct"]
    path, st = _state(cfg)
    today = datetime.now(AR).strftime("%Y-%m-%d")
    msgs = []
    for item, sig, chg in changes(cfg, results):
        if abs(chg) < thr:
            continue
        key = f"{today}|move|{sig.symbol}"
        if st.get(key):
            continue
        st[key] = True
        msgs.append(_line(item, sig, chg, offline))
    if msgs:
        notify(f"⚡ <b>Movimientos fuertes (más de {thr:.0%} en el día)</b>\n" + "\n".join(msgs)
               + "\nNo es consejo financiero. DYOR.")
        with open(path, "w") as f:
            json.dump(st, f)
