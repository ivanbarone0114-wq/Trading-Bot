"""Datos de la pestaña Terminal: macro argentina, mercados globales, noticias y calendario.
Se guardan en state/terminal.json con vencimiento por bloque, así no se piden en cada ciclo."""
import json, os, time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import requests

AR = ZoneInfo("America/Argentina/Buenos_Aires")
TTL = {"macro": 30 * 60, "global": 30 * 60, "news": 30 * 60, "earnings": 12 * 3600, "renta": 30 * 60}
MESES = {"E": 1, "F": 2, "M": 3, "A": 4, "Y": 5, "J": 6, "L": 7, "G": 8, "S": 9, "O": 10, "N": 11, "D": 12}
SOBERANOS = ["AL30", "GD30", "AL35", "GD35", "AE38", "GD38", "AL41", "GD41", "GD46"]
GLOBAL = [("S&P 500", "^GSPC"), ("Nasdaq 100", "^NDX"), ("Merval (ARS)", "^MERV"), ("Bitcoin", "BTC-USD"),
          ("Oro", "GC=F"), ("Petróleo WTI", "CL=F"), ("Dólar índice (DXY)", "DX-Y.NYB"), ("Tasa 10 años EE.UU.", "^TNX"),
          ("Real/dólar", "BRL=X"), ("Soja (CBOT)", "ZS=F")]
NEWS = [("Argentina", "BCRA OR \"riesgo país\" OR Merval OR \"dólar\" when:1d"),
        ("Wall Street", "\"Wall Street\" OR \"S&P 500\" OR Fed when:1d"),
        ("Cripto", "bitcoin OR ethereum OR cripto when:1d")]
FOMC = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"]


def _get(url, timeout=12):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "trading-bot/1.0"})
    r.raise_for_status()
    return r.json()


def _macro():
    out = {}
    try:
        d = {x["casa"]: x for x in _get("https://dolarapi.com/v1/dolares")}
        names = [("oficial", "Oficial"), ("bolsa", "MEP"), ("contadoconliqui", "CCL"), ("blue", "Blue"),
                 ("cripto", "Cripto"), ("mayorista", "Mayorista"), ("tarjeta", "Tarjeta")]
        out["dolares"] = [{"nombre": n, "compra": d[k].get("compra"), "venta": d[k].get("venta"),
                           "fecha": d[k].get("fechaActualizacion")} for k, n in names if k in d]
        of, ccl = d.get("oficial", {}).get("venta"), d.get("contadoconliqui", {}).get("venta")
        if of and ccl:
            out["brecha_ccl"] = ccl / of - 1
    except Exception as e:
        print(f"[terminal] dólares: {type(e).__name__}")
    try:
        rp = _get("https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais/ultimo")
        out["riesgo_pais"] = {"valor": rp.get("valor"), "fecha": rp.get("fecha")}
    except Exception as e:
        print(f"[terminal] riesgo país: {type(e).__name__}")
    try:
        inf = _get("https://api.argentinadatos.com/v1/finanzas/indices/inflacion")[-13:]
        last = inf[-1]
        yoy = 1.0
        for x in inf[-12:]:
            yoy *= 1 + float(x["valor"]) / 100
        out["inflacion"] = {"mes": last["fecha"][:7], "valor": float(last["valor"]) / 100, "interanual": yoy - 1,
                            "serie": [{"m": x["fecha"][:7], "v": float(x["valor"]) / 100} for x in inf[-12:]]}
    except Exception as e:
        print(f"[terminal] inflación: {type(e).__name__}")
    try:
        pf = _get("https://api.argentinadatos.com/v1/finanzas/tasas/plazoFijo")
        rates = sorted([(x["entidad"], float(x["tnaClientes"])) for x in pf if x.get("tnaClientes")], key=lambda r: -r[1])
        if rates:
            avg = sum(r for _, r in rates) / len(rates)
            out["plazo_fijo"] = {"promedio_tna": avg, "tem": avg * 30 / 365, "mejores": rates[:3], "n": len(rates)}
    except Exception as e:
        print(f"[terminal] plazo fijo: {type(e).__name__}")
    if out.get("inflacion") and out.get("plazo_fijo"):
        out["tasa_real_mensual"] = (1 + out["plazo_fijo"]["tem"]) / (1 + out["inflacion"]["valor"]) - 1
    return out


def _global(offline=False):
    if offline:
        return []
    import yfinance as yf
    rows = []
    for name, tk in GLOBAL:
        try:
            df = yf.download(tk, period="1mo", interval="1d", progress=False, auto_adjust=True)
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
            c = df["Close"].dropna()
            if len(c) < 2:
                continue
            last = float(c.iloc[-1])
            rows.append({"nombre": name, "ticker": tk, "ultimo": last, "dia": last / float(c.iloc[-2]) - 1,
                         "semana": last / float(c.iloc[-6]) - 1 if len(c) > 5 else None,
                         "mes": last / float(c.iloc[0]) - 1, "spark": [round(float(x), 4) for x in c.tail(22)],
                         "fecha": str(c.index[-1].date())})
        except Exception as e:
            print(f"[terminal] {tk}: {type(e).__name__}")
    return rows


def _news(offline=False):
    if offline:
        return []
    try:
        import feedparser
        from urllib.parse import quote_plus
    except ImportError:
        return []
    out = []
    for tema, q in NEWS:
        try:
            feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=es-419&gl=AR&ceid=AR:es-419")
            for e in feed.entries[:6]:
                src = getattr(getattr(e, "source", None), "title", "") if hasattr(e, "source") else ""
                t = time.mktime(e.published_parsed) if getattr(e, "published_parsed", None) else None
                out.append({"tema": tema, "titulo": e.title, "link": e.link, "fuente": src,
                            "ts": datetime.fromtimestamp(t, AR).strftime("%d/%m %H:%M") if t else ""})
        except Exception as ex:
            print(f"[terminal] noticias {tema}: {type(ex).__name__}")
    return out


def _vto_letra(sym):
    """Fecha de vencimiento de una letra por su código (S30N6 = 30 de noviembre de 2026)."""
    import re
    m = re.fullmatch(r"[SXD](\d{1,2})([EFMAYJLGSOND])(\d)", sym)
    if not m:
        return None
    try:
        return date(2020 + int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def _renta_fija(cfg):
    """Letras, bonos soberanos y ONs desde data912.com (precios con unos 20 s de demora, sin garantía)."""
    rf = cfg.get("renta_fija") or {}
    pagos = {k.upper(): float(v) for k, v in (rf.get("pagos") or {}).items()}
    out = {}
    today = datetime.now(AR).date()
    tipo = {"S": "Lecap (tasa fija)", "X": "CER (inflación)", "D": "Dólar linked"}
    try:
        letras = []
        for x in _get("https://data912.com/live/arg_notes"):
            vto = _vto_letra(x["symbol"])
            if not vto or not x.get("c") or vto <= today:
                continue
            dias = (vto - today).days
            row = {"symbol": x["symbol"], "tipo": tipo[x["symbol"][0]], "precio": x["c"], "var": (x.get("pct_change") or 0) / 100,
                   "vol": x.get("v") or 0, "vto": str(vto), "dias": dias}
            pago = pagos.get(x["symbol"])
            if pago and x["symbol"][0] == "S":
                tem = (pago / x["c"]) ** (30 / dias) - 1
                row.update(tem=tem, tna=tem * 365 / 30, tea=(1 + tem) ** (365 / 30) - 1)
            letras.append(row)
        out["letras"] = sorted(letras, key=lambda r: r["dias"])
    except Exception as e:
        print(f"[terminal] letras: {type(e).__name__}")
    try:
        b = {x["symbol"]: x for x in _get("https://data912.com/live/arg_bonds")}
        rows = []
        for s in SOBERANOS:
            ars, usd = b.get(s), b.get(s + "D")
            if ars and usd and ars.get("c") and usd.get("c"):
                rows.append({"symbol": s, "ars": ars["c"], "usd": usd["c"], "var": (usd.get("pct_change") or 0) / 100,
                             "mep": ars["c"] / usd["c"], "vol": usd.get("v") or 0})
        out["soberanos"] = rows
        al = next((r for r in rows if r["symbol"] == "AL30"), None)
        if al:
            out["mep_al30"] = al["mep"]
    except Exception as e:
        print(f"[terminal] bonos: {type(e).__name__}")
    try:
        ons = [x for x in _get("https://data912.com/live/arg_corp") if x["symbol"].endswith("D") and x.get("c") and x.get("v")]
        out["ons"] = [{"symbol": x["symbol"], "precio": x["c"], "var": (x.get("pct_change") or 0) / 100, "vol": x["v"]}
                      for x in sorted(ons, key=lambda x: -x["v"])[:15]]
    except Exception as e:
        print(f"[terminal] ONs: {type(e).__name__}")
    return out


def _earnings(tickers, offline=False):
    if offline or not tickers:
        return []
    import yfinance as yf
    out, today = [], date.today()
    for tk in tickers[:30]:
        try:
            cal = yf.Ticker(tk).calendar
            dates = (cal or {}).get("Earnings Date") if isinstance(cal, dict) else None
            for d in dates or []:
                d = d if isinstance(d, date) else datetime.fromisoformat(str(d)).date()
                if today <= d <= today + timedelta(days=30):
                    out.append({"fecha": str(d), "evento": f"Balance de {tk}", "tipo": "balance"})
                    break
        except Exception as e:
            print(f"[terminal] balance {tk}: {type(e).__name__}")
    return out


def update(cfg, held_us, offline=False):
    """Refresca los bloques vencidos y devuelve todo lo guardado."""
    path = os.path.join(cfg["state_dir"], "terminal.json")
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
    now = time.time()
    us_watch = sorted({w["symbol"] for w in cfg.get("watchlist") or [] if w["market"] == "us"} | set(held_us))
    jobs = {"macro": lambda: {} if offline else _macro(), "global": lambda: _global(offline),
            "news": lambda: _news(offline), "earnings": lambda: _earnings(us_watch, offline),
            "renta": lambda: {} if offline else _renta_fija(cfg)}
    for k, fn in jobs.items():
        if now - data.get(f"{k}_ts", 0) >= TTL[k]:
            val = fn()
            if val or k not in data:  # si falla, se conserva el último dato bueno
                data[k], data[f"{k}_ts"] = val, now
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    return data


def calendar(cfg, earnings):
    today = datetime.now(AR).date()
    ev = [{"fecha": d, "evento": "Decisión de tasas de la Fed (FOMC)", "tipo": "fed"} for d in FOMC
          if today <= date.fromisoformat(d) <= today + timedelta(days=60)]
    for e in (cfg.get("calendario") or []):
        try:
            if today <= date.fromisoformat(str(e["fecha"])) <= today + timedelta(days=60):
                ev.append({"fecha": str(e["fecha"]), "evento": e["evento"], "tipo": "propio"})
        except Exception:
            pass
    ev += earnings or []
    return sorted(ev, key=lambda x: x["fecha"])[:20]
