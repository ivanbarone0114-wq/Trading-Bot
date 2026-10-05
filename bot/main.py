"""CLI del bot.
  python -m bot.main scan                 → alertas (sin operar)
  python -m bot.main run [--loop 3600]    → ciclo según 'mode' del config (alerts/paper/live)
  python -m bot.main decide ...           → registrás tu decisión y recibís consejos
  python -m bot.main backtest ...         → prueba histórica
  python -m bot.main status               → cartera simulada
Agregá --offline para probar con datos sintéticos."""
import argparse, json, os, re, sys, time
import yaml

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from .data import fetch_ohlcv, load_csv
from .strategy import evaluate
from .news import news_sentiment
from .risk import RiskManager
from .journal import Journal
from .advisor import advise
from .notifier import notify
from .brokers.paper import PaperBroker
from . import backtest as bt
from .ccl import ccl_lines, implied_ccl
from .cedears import arbitrage, cedear_list
from .explain import explain_entry, explain_exit, dumps
from .panel import record_equity, write_panel
from .strategy import prepare
from .informe import build_report, equity_by_market, save_equity_snapshot


def _numbers(d):
    """Acepta números escritos con coma decimal ("0,34") en la configuración."""
    for k, v in d.items():
        if isinstance(v, dict):
            _numbers(v)
        elif isinstance(v, str) and re.fullmatch(r"\s*-?\d+([.,]\d+)?\s*", v):
            d[k] = float(v.strip().replace(",", "."))
            print(f"[config] '{k}: {v}' tiene coma decimal; se toma como {d[k]}. Conviene escribirlo con punto.")


def load_cfg(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for sec in ("capital", "risk", "strategy"):
        if isinstance(cfg.get(sec), dict):
            _numbers(cfg[sec])
    return cfg


def strategy_for(cfg, market):
    """Estrategia general con los ajustes propios de cada mercado (strategy_overrides)."""
    import copy
    st = copy.deepcopy(cfg["strategy"])
    for k, v in ((cfg.get("strategy_overrides") or {}).get(market) or {}).items():
        if isinstance(v, dict) and isinstance(st.get(k), dict):
            st[k].update(v)
        else:
            st[k] = v
    return st


def analyze(item, cfg, offline):
    df = fetch_ohlcv(item["symbol"], item["market"], item["timeframe"], 500, offline)
    df_htf = fetch_ohlcv(item["symbol"], item["market"], item["htf"], 200, offline) if item.get("htf") else None
    ns, titles = (None, [])
    if cfg["news"]["enabled"] and not offline:
        ns, titles = news_sentiment(item.get("keywords"), cfg["news"]["max_items"])
    label = item["symbol"] + ".BA" if item["market"] == "byma" and not item["symbol"].endswith(".BA") else item["symbol"]
    sig = evaluate(df, strategy_for(cfg, item["market"]), label, ns, df_htf)
    return sig, df, titles


def get_brokers(cfg, mode, confirm_live):
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"], cfg.get("fees"))
    if mode != "live":
        return {"crypto": paper, "us": paper, "byma": paper}
    if not (cfg["live"]["enabled"] and confirm_live):
        sys.exit("Modo live bloqueado: requiere live.enabled: true en config Y el flag --confirm-live.")
    from .brokers.binance_live import BinanceBroker
    from .brokers.alpaca_live import AlpacaBroker
    return {"crypto": BinanceBroker(cfg["live"]["crypto_testnet"]),
            "us": AlpacaBroker(cfg["live"]["alpaca_paper"]),
            "byma": paper}  # BYMA sigue en paper hasta implementar broker local


def confirm(msg, cfg, mode):
    if mode != "live" or cfg["live"]["auto_confirm"]:
        return True
    return input(f"{msg} ¿Confirmás? (si/no): ").strip().lower() in ("si", "sí", "s", "y")


def alerted_before(state_dir, sig):
    path = os.path.join(state_dir, "alerts.json")
    seen = json.load(open(path)) if os.path.exists(path) else {}
    key = f"{sig.symbol}|{sig.bar_time}|{sig.action}"
    if seen.get(sig.symbol) == key:
        return True
    seen[sig.symbol] = key
    json.dump(seen, open(path, "w"), indent=2)
    return False


def items_of(cfg, markets=None):
    """Watchlist + universo + CEDEARs (sin duplicados). markets filtra, ej. {"crypto"}."""
    return [it for it in _all_items(cfg) if not markets or it["market"] in markets]


def _all_items(cfg):
    items = list(cfg.get("watchlist") or [])
    seen = {(w["symbol"], w["market"]) for w in items}
    uni = cfg.get("universe") or {}
    for mkt in ("us", "byma", "crypto"):
        for sym in uni.get(mkt) or []:
            if (sym, mkt) not in seen:
                seen.add((sym, mkt))
                items.append({"symbol": sym, "market": mkt,
                              "timeframe": uni.get("timeframe", "4h" if mkt == "crypto" else "1d"),
                              "htf": uni.get("htf", "1d" if mkt == "crypto" else "1wk")})
    if (cfg.get("cedears") or {}).get("trade", True):
        for c in cedear_list(cfg):
            if (c["symbol"], "byma") not in seen:
                seen.add((c["symbol"], "byma"))
                items.append({"symbol": c["symbol"], "market": "byma", "timeframe": "1d", "htf": "1wk"})
    return items


EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}


def sig_line(s):
    return f"{EMOJI[s.action]} <b>{s.symbol}</b> {s.action} ({s.score:+.2f}) | {s.price:,.2f} | RSI {s.rsi:.0f}"


def ranking_lines(sigs, full_limit=14, top=5):
    """Lista completa si son pocos activos; si son muchos, solo los mejores y los más débiles."""
    if len(sigs) <= full_limit:
        return [sig_line(s) for s in sigs]
    nb = sum(s.action == "BUY" for s in sigs)
    ns = sum(s.action == "SELL" for s in sigs)
    best = sorted([s for s in sigs if s.score > 0], key=lambda s: -s.score)[:top]
    worst = sorted([s for s in sigs if s.score < 0], key=lambda s: s.score)[:top]
    out = [f"Analizados {len(sigs)} activos: 🟢 {nb} compra, 🔴 {ns} venta, ⚪ {len(sigs) - nb - ns} neutrales",
           "", "🔝 <b>Mejores candidatos a compra</b>"]
    out += [sig_line(s) for s in best] or ["Ninguno con score positivo"]
    out += ["", "🔻 <b>Más débiles</b>"]
    out += [sig_line(s) for s in worst] or ["Ninguno con score negativo"]
    return out


def cycle(cfg, mode, offline, confirm_live=False, summary=False, quiet=False, markets=None):
    j = Journal(cfg["state_dir"])
    risk = RiskManager(cfg["risk"], cfg["capital"], cfg["state_dir"])
    brokers = get_brokers(cfg, mode, confirm_live) if mode in ("paper", "live") else None
    results, last_px, px_cache = [], {}, {}
    ops = {"buy": 0, "sell": 0}

    # 1) analizar todo
    for item in items_of(cfg, markets):
        mkt = item["market"]
        try:
            sig, df, _ = analyze(item, cfg, offline)
        except Exception as e:
            print(f"[{item['symbol']}] error de datos: {e}")
            continue
        sym = sig.symbol
        px_cache[sym] = (float(df["close"].iloc[-1]), df.index[-1].date())
        last_px[sym] = float(df["close"].iloc[-1])
        results.append((item, sig, df))
        if sig.action != "HOLD" and not alerted_before(cfg["state_dir"], sig):
            if not summary and not quiet:
                notify(sig.text())
            j.log(kind="alert", mode=mode, symbol=sym, market=mkt, side=sig.action, price=sig.price,
                  stop=sig.stop or "", target=sig.target or "", note=f"score {sig.score}")

    if brokers:
        # 2) salidas primero: liberan efectivo y cupos
        for item, sig, df in results:
            mkt, sym, last = item["market"], sig.symbol, df.iloc[-1]
            b = brokers[mkt]
            pos = b.position(sym)
            if not (pos and pos["qty"] > 0):
                continue
            why = None
            if pos.get("stop") and last["low"] <= pos["stop"]:
                why, px = "stop", pos["stop"]
            elif pos.get("target") and last["high"] >= pos["target"]:
                why, px = "objetivo", pos["target"]
            elif sig.action == "SELL":
                why, px = "señal", sig.price
            if why and confirm(f"[{mode}] VENDER {pos['qty']:.6f} {sym} @ {px:,.4f} ({why}).", cfg, mode):
                sold_qty = float(pos["qty"])  # se guarda antes: la venta modifica la posición
                ops["sell"] += 1
                try:
                    detail = dumps(explain_exit(why, dict(pos), px, sig, None))
                except Exception as e:
                    detail = ""; print(f"[{sym}] sin detalle: {e}")
                pnl, fill = b.sell(sym, mkt, sold_qty, px)
                j.log(kind="trade", mode=mode, symbol=sym, market=mkt, side="sell", qty=sold_qty,
                      price=fill, pnl=pnl if pnl is not None else "", note=why, detail=detail)
                notify(f"🔴 [{mode}] Venta {sym} @ {fill:,.4f} ({why})" + (f" | PnL {pnl:+,.2f}" if pnl is not None else ""))

        # 3) entradas: las señales más fuertes primero
        buys = sorted([r for r in results if r[1].action == "BUY"], key=lambda r: -r[1].score)
        for item, sig, df in buys:
            mkt, sym = item["market"], sig.symbol
            b = brokers[mkt]
            if b.position(sym):
                continue
            ok, reason = risk.can_open(mkt, b.open_count(mkt), j.realized_today(mkt))
            if not ok:
                print(f"[{sym}] compra bloqueada: {reason}")
                continue
            qty = risk.size(mkt, sig.price, sig.stop, b.cash(mkt))
            if mkt == "byma":
                qty = float(int(qty))  # en BYMA se compran acciones enteras
            if qty <= 0:
                print(f"[{sym}] sin efectivo suficiente para comprar")
                continue
            if confirm(f"[{mode}] COMPRAR {qty:.6f} {sym} @ ~{sig.price:,.4f} (stop {sig.stop:,.4f}).", cfg, mode):
                try:
                    fill = b.buy(sym, mkt, qty, sig.price, sig.stop, sig.target)
                except Exception as e:
                    print(f"[{sym}] compra no ejecutada: {e}")
                    continue
                try:
                    st = strategy_for(cfg, mkt)
                    detail = dumps(explain_entry(sig, prepare(df, st).iloc[-1], df, {"strategy": st}))
                except Exception as e:
                    detail = ""; print(f"[{sym}] sin detalle: {e}")
                j.log(kind="trade", mode=mode, symbol=sym, market=mkt, side="buy", qty=qty, price=fill,
                      stop=sig.stop, target=sig.target, note=f"score {sig.score}", detail=detail)
                ops["buy"] += 1
                notify(f"🟢 [{mode}] Compra {qty:.4f} {sym} @ {fill:,.4f} | score {sig.score:+.2f} | "
                       f"stop {sig.stop:,.4f} | obj {sig.target:,.4f}")

    if summary and results:
        from datetime import datetime
        extra = paper_lines(brokers["crypto"], last_px, j) if mode == "paper" and brokers else []
        if cfg.get("ccl", {}).get("enabled", True):
            extra = ccl_lines(cfg, px_cache, offline) + extra
        notify(f"📊 <b>Resumen {datetime.now():%d/%m %H:%M}</b>\n"
               + "\n".join(ranking_lines([r[1] for r in results]) + extra) + "\n⚠️ No es consejo financiero. DYOR.")

    if results and any(r[0]["market"] == "byma" for r in results):
        arb_alerts(cfg, px_cache, offline)
    if mode == "paper" and brokers and results:
        refresh_panel(cfg, brokers["crypto"], j, results, px_cache, last_px, offline, record=True)
    return ops, len(results)


def refresh_panel(cfg, paper, j, results, px_cache, last_px, offline=False, record=False):
    """Combina lo analizado ahora con lo último conocido de los otros mercados y regenera el panel."""
    from datetime import date
    from .panel import load_cache, save_cache, sig_row
    try:
        cache = load_cache(cfg["state_dir"])
        for sym, (p, d) in px_cache.items():
            cache["px"][sym] = [p, str(d)]
        for item, sig, df in results:
            cache["sig"][sig.symbol] = sig_row(item, sig, df, strategy_for(cfg, item["market"]))
        save_cache(cfg["state_dir"], cache)
        all_px = {k: (v[0], date.fromisoformat(v[1])) for k, v in cache["px"].items()}
        all_last = {k: v[0] for k, v in cache["px"].items()}
        if record:
            _, ccl = implied_ccl(cfg, dict(all_px), offline)
            record_equity(cfg["state_dir"], paper, all_last, ccl)
        write_panel(cfg, paper, j, results, dict(all_px), all_last, offline, sig_rows=list(cache["sig"].values()))
    except Exception as e:
        print(f"[panel] no se pudo generar: {e}")


def arb_alerts(cfg, px_cache, offline=False):
    """Avisa una vez por día y por CEDEAR cuando el CCL implícito se desvía del de referencia."""
    if not cedear_list(cfg):
        return
    from datetime import datetime
    try:
        rows, ref, src, thr = arbitrage(cfg, px_cache, offline)
    except Exception as e:
        print(f"[arbitraje] {e}")
        return
    path = os.path.join(cfg["state_dir"], "alerts.json")
    seen = json.load(open(path)) if os.path.exists(path) else {}
    today = datetime.now().strftime("%Y-%m-%d")
    msgs = []
    for r in rows:
        if r["kind"] not in ("cheap", "rich"):
            continue
        key = f"{today}|{r['kind']}"
        if seen.get("ARB:" + r["symbol"]) == key:
            continue
        seen["ARB:" + r["symbol"]] = key
        msgs.append(f"{'🟢' if r['kind'] == 'cheap' else '🔴'} <b>{r['symbol']}</b>: CCL implícito ${r['ccl']:,.2f} "
                    f"({r['dev']:+.1%} vs ${ref:,.2f}). {r['read']}")
    if msgs:
        json.dump(seen, open(path, "w"), indent=2)
        notify("⚖️ <b>Desvíos de CEDEARs contra el CCL</b>\n" + "\n".join(msgs)
               + "\nPrecios con demora y sin comisiones: verificá en tu broker antes de operar.")


def paper_lines(paper, last_px, j):
    """Estado de la cartera simulada para el resumen."""
    out = ["", "💼 <b>Cartera simulada</b>"]
    pos = paper.s["positions"]
    if not pos:
        out.append("Sin posiciones abiertas")
    for sym, p in pos.items():
        px = last_px.get(sym, p["avg"])
        out.append(f"{sym}: {p['qty']:.4f} @ {p['avg']:,.2f} → {px:,.2f} ({(px / p['avg'] - 1):+.2%})")
    realized = sum(float(r["pnl"]) for r in j.rows_since(3650) if r["kind"] == "trade" and r["mode"] == "paper" and r["pnl"])
    cash = ", ".join(f"{m} {c:,.0f}" for m, c in paper.s["cash"].items())
    out += [f"Efectivo: {cash}", f"PnL realizado acumulado: {realized:+,.2f}"]
    return out


def scan_all(cfg, offline=False, markets=None):
    results, px_cache, last_px = [], {}, {}
    for item in items_of(cfg, markets):
        try:
            sig, df, _ = analyze(item, cfg, offline)
        except Exception as e:
            print(f"[{item['symbol']}] error de datos: {e}")
            continue
        px = float(df["close"].iloc[-1])
        px_cache[sig.symbol] = (px, df.index[-1].date())
        last_px[sig.symbol] = px
        results.append((item, sig, df))
    return results, px_cache, last_px


def cmd_panel(cfg, offline=False):
    j = Journal(cfg["state_dir"])
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
    results, px_cache, last_px = scan_all(cfg, offline)
    refresh_panel(cfg, paper, j, results, px_cache, last_px, offline)
    print("Panel actualizado: state/panel.html")


def cmd_daily(cfg, offline=False):
    """Resumen de cierre: señales, operaciones del día, CCL y cartera. No opera."""
    from datetime import datetime
    j = Journal(cfg["state_dir"])
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
    results, px_cache, last_px = scan_all(cfg, offline)
    sigs = [r[1] for r in results]
    lines = ranking_lines(sigs)

    today = datetime.now().date()
    ops = []
    for r in j.rows_since(2):
        if r["kind"] != "trade" or r["mode"] != "paper":
            continue
        if datetime.fromisoformat(r["time"]).astimezone().date() != today:
            continue
        if r["side"] == "buy":
            ops.append(f"🟢 Compra {r['symbol']} {float(r['qty']):.4f} @ {float(r['price']):,.2f}")
        else:
            pnl = f" | PnL {float(r['pnl']):+,.2f}" if r["pnl"] else ""
            ops.append(f"🔴 Venta {r['symbol']} @ {float(r['price']):,.2f} ({r['note']}){pnl}")
    ops_block = ["", "🧾 <b>Operaciones de hoy</b>"] + (ops or ["Sin operaciones"])

    extra = ops_block
    if cfg.get("ccl", {}).get("enabled", True):
        extra += ccl_lines(cfg, px_cache, offline)
    try:
        _, ccl_avg = implied_ccl(cfg, px_cache, offline)
        save_equity_snapshot(cfg["state_dir"], equity_by_market(paper, last_px), ccl_avg)
    except Exception as e:
        print(f"[equity] {e}")
    refresh_panel(cfg, paper, j, results, px_cache, last_px, offline)
    extra += paper_lines(paper, last_px, j)
    notify(f"🌙 <b>Resumen del día {datetime.now():%d/%m}</b>\n" + "\n".join(lines + extra)
           + "\n⚠️ No es consejo financiero. DYOR.")


CRYPTO_BASES = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "DOT", "AVAX", "LINK", "LTC", "TRX", "MATIC", "POL", "TON", "USDT"}


def resolve_symbol(raw, cfg):
    """Devuelve [(símbolo, mercado), ...]. GGAL.BA → BYMA; BTC o BTC/USDT → cripto;
    si el ticker existe en varios mercados (GGAL), devuelve todos."""
    s = re.sub(r"[^A-Za-z0-9./-]", "", raw or "").upper()
    if not s:
        return []
    if "/" in s:
        return [(s, "crypto")]
    if s in CRYPTO_BASES:
        return [(f"{s}/USDT", "crypto")]
    if s.endswith(".BA"):
        return [(s[:-3], "byma")]
    found = [(it["symbol"], it["market"]) for it in items_of(cfg) if it["symbol"].upper() == s]
    return found or [(s, "us")]


def quote_text(sym, mkt, cfg, offline=False):
    item = next((it for it in items_of(cfg) if it["symbol"].upper() == sym.upper() and it["market"] == mkt), None) \
        or {"symbol": sym, "market": mkt, "timeframe": "4h" if mkt == "crypto" else "1d",
            "htf": "1d" if mkt == "crypto" else "1wk"}
    sig, df, titles = analyze(item, cfg, offline)
    daily = df if item["timeframe"] == "1d" else fetch_ohlcv(sym, mkt, "1d", 60, offline)
    c = daily["close"]
    chg = lambda n: f"{c.iloc[-1] / c.iloc[-1 - n] - 1:+.1%}" if len(c) > n else "s/d"
    cur = {"crypto": "USDT", "us": "USD", "byma": "ARS"}[mkt]
    trend = {1: "alcista", -1: "bajista", 0: "lateral"}
    from .strategy import prepare, trend_of
    d = prepare(df, strategy_for(cfg, mkt))
    last = d.iloc[-1]
    win = df.tail(50)
    lines = [f"💹 <b>{sig.symbol}</b> ({ {'crypto': 'Cripto', 'us': 'EE.UU.', 'byma': 'BYMA'}[mkt] }): {sig.price:,.2f} {cur}",
             f"Día {chg(1)} | 5 ruedas {chg(5)} | 1 mes {chg(21)}",
             f"Señal: {EMOJI[sig.action]} {sig.action} (score {sig.score:+.2f})",
             f"RSI {sig.rsi:.0f} | MACD {'↑' if last['macd_hist'] > 0 else '↓'} | Tendencia {trend[trend_of(last)]}",
             f"Soporte {win['low'].min():,.2f} | Resistencia {win['high'].max():,.2f}",
             f"Stop técnico (ATR): {sig.price - cfg['strategy']['atr_stop_mult'] * sig.atr:,.2f}"]
    paper = PaperBroker(cfg["state_dir"], cfg["capital"])
    pos = paper.position(sig.symbol)
    if pos:
        lines.append(f"📌 En cartera: {pos['qty']:.4f} @ {pos['avg']:,.2f} ({sig.price / pos['avg'] - 1:+.2%})")
    lines += [f"• {r}" for r in sig.reasons]
    if titles:
        lines.append("📰 " + titles[0][:120])
    return "\n".join(lines)


def cmd_quote(cfg, raw, offline=False):
    pairs = resolve_symbol(raw, cfg)
    if not pairs:
        notify("Decime qué símbolo cotizar, por ejemplo: /cotizacion GGAL")
        return
    blocks = []
    for sym, mkt in pairs:
        try:
            blocks.append(quote_text(sym, mkt, cfg, offline))
        except Exception as e:
            print(f"[cotizacion] {sym} {mkt}: {e}")
            blocks.append(f"❌ No encontré datos de {sym} en {mkt}. Para BYMA usá .BA (ej. GGAL.BA); para cripto, BTC o BTC/USDT.")
    notify("\n\n".join(blocks) + "\n⚠️ No es consejo financiero. DYOR.")


def current_prices(paper, offline=False):
    """Último precio de cada posición abierta."""
    last_px = {}
    for label, p in paper.s["positions"].items():
        sym = label[:-3] if label.endswith(".BA") else label
        try:
            last_px[label] = float(fetch_ohlcv(sym, p["market"], "1d", 5, offline)["close"].iloc[-1])
        except Exception as e:
            print(f"[precios] {label}: {e}")
    return last_px


def cmd_portfolio(cfg, offline=False):
    from datetime import datetime
    j = Journal(cfg["state_dir"])
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
    last_px = current_prices(paper, offline)
    notify(f"💼 <b>Cartera {datetime.now():%d/%m %H:%M}</b>\n" + "\n".join(paper_lines(paper, last_px, j)[2:]))


def cmd_informe(cfg, dias=7, offline=False):
    from datetime import datetime
    from .notifier import send_document
    j = Journal(cfg["state_dir"])
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
    ccl_rows = None
    if cfg.get("ccl", {}).get("enabled", True):
        try:
            ccl_rows, _ = implied_ccl(cfg, {}, offline)
            ccl_rows = [(n, v, note) for n, v, note in ccl_rows]
        except Exception as e:
            print(f"[informe] ccl: {e}")
    md, sm = build_report(cfg, paper, j, analyze, items_of(cfg), dias, offline, ccl_rows)
    os.makedirs(cfg["state_dir"], exist_ok=True)
    fname = f"informe_{datetime.now():%Y-%m-%d}.md"
    for path in (os.path.join(cfg["state_dir"], fname), os.path.join(cfg["state_dir"], "informe.md")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
    st = sm["stats"]
    lines = [f"📑 <b>Informe de análisis, últimos {dias} días</b>"]
    for m in ("crypto", "us", "byma"):
        cap = sm["cap"][m]
        if cap:
            lines.append(f"{m}: patrimonio {sm['eq'].get(m, 0):,.2f} ({sm['eq'].get(m, 0) / cap - 1:+.2%})")
    lines.append(f"Operaciones cerradas: {sm['closed']}" + (f" | acierto {st['win_rate']:.0%}" if st else ""))
    lines.append(f"Posiciones abiertas: {sm['open']}")
    lines.append("📎 El informe completo va adjunto en Telegram y queda en GitHub: state/informe.md. "
                 "Pegalo en un chat de análisis junto con el prompt que trae al final.")
    notify("\n".join(lines))
    send_document(os.path.join(cfg["state_dir"], fname), f"Informe {datetime.now():%d/%m/%Y}")


def cmd_report(cfg, a):
    j = Journal(cfg["state_dir"])
    rows = [r for r in j.rows_since(a.dias) if r["mode"] == "paper"]
    trades = [r for r in rows if r["kind"] == "trade"]
    buys = [r for r in trades if r["side"] == "buy"]
    sells = [r for r in trades if r["side"] == "sell" and r["pnl"]]
    wins = [r for r in sells if float(r["pnl"]) > 0]
    by_mkt = {}
    for r in sells:
        by_mkt[r["market"]] = by_mkt.get(r["market"], 0.0) + float(r["pnl"])
    paper = PaperBroker(cfg["state_dir"], cfg["capital"])
    lines = [f"📈 <b>Reporte paper, últimos {a.dias} días</b>",
             f"Compras: {len(buys)} | Ventas cerradas: {len(sells)}",
             f"Acierto: {len(wins) / len(sells):.0%}" if sells else "Acierto: sin operaciones cerradas"]
    lines += [f"PnL {m}: {v:+,.2f}" for m, v in by_mkt.items()]
    motivos = {}
    for r in sells:
        motivos[r["note"]] = motivos.get(r["note"], 0) + 1
    if motivos:
        lines.append("Cierres por: " + ", ".join(f"{k} {v}" for k, v in motivos.items()))
    lines += paper_lines(paper, current_prices(paper, getattr(a, "offline", False)), j)[1:]
    if cfg.get("ccl", {}).get("enabled", True):
        lines += ccl_lines(cfg, {}, getattr(a, "offline", False))
    lines.append("⚠️ No es consejo financiero. DYOR.")
    notify("\n".join(lines))


def maybe_weekly_report(cfg, offline=False):
    """Manda el reporte una vez por semana, en el primer ciclo desde el día y hora configurados."""
    from datetime import datetime
    wr = cfg.get("weekly_report", {})
    if not wr.get("enabled", True):
        return
    now = datetime.now()
    if now.weekday() != wr.get("weekday", 6) or now.hour < wr.get("hour", 20):
        return
    flag = os.path.join(cfg["state_dir"], "last_weekly_report.txt")
    week = now.strftime("%G-W%V")
    if os.path.exists(flag) and open(flag).read().strip() == week:
        return
    cmd_report(cfg, argparse.Namespace(dias=wr.get("days", 7), offline=offline))
    with open(flag, "w") as f:
        f.write(week)


def cmd_decide(cfg, a):
    item = next((w for w in cfg["watchlist"] if w["symbol"] == a.symbol), None) or \
        {"symbol": a.symbol, "market": a.market, "timeframe": "1d", "htf": "1wk", "keywords": [a.symbol]}
    item["market"] = a.market or item["market"]
    sig, _, titles = analyze(item, cfg, a.offline)
    price = a.price or sig.price
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
    pos = paper.position(a.symbol)
    tips = advise({"side": a.side, "price": price, "qty": a.qty, "stop": a.stop}, sig, cfg["risk"],
                  cfg["capital"][item["market"]], pos["qty"] if pos else 0.0, titles,
                  cfg["strategy"]["atr_stop_mult"])
    print(sig.text().replace("<b>", "").replace("</b>", ""), "\n\n== Consejos ==")
    print("\n".join(tips))
    Journal(cfg["state_dir"]).log(kind="decision", mode="manual", symbol=a.symbol, market=item["market"],
                                  side=a.side, qty=a.qty, price=price, stop=a.stop or "",
                                  note=f"señal {sig.action} {sig.score:+.2f}")
    if a.execute_paper:
        j = Journal(cfg["state_dir"])
        if a.side == "buy":
            stop = a.stop or sig.stop or price - cfg["strategy"]["atr_stop_mult"] * sig.atr
            target = price + cfg["strategy"]["reward_risk"] * (price - stop)
            fill = paper.buy(a.symbol, item["market"], a.qty, price, stop, target)
            j.log(kind="trade", mode="paper", symbol=a.symbol, market=item["market"], side="buy",
                  qty=a.qty, price=fill, stop=stop, target=target, note="manual")
        else:
            pnl, fill = paper.sell(a.symbol, item["market"], a.qty, price)
            j.log(kind="trade", mode="paper", symbol=a.symbol, market=item["market"], side="sell",
                  qty=a.qty, price=fill, pnl=pnl, note="manual")
        print("→ Ejecutado en la cartera simulada.")


def main():
    p = argparse.ArgumentParser(description="Bot de trading: alertas, paper y live")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--offline", action="store_true", help="datos sintéticos, sin internet")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan")
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=["alerts", "paper", "live"])
    r.add_argument("--loop", type=int, default=0, help="segundos entre ciclos (0 = una vez)")
    r.add_argument("--confirm-live", action="store_true")
    r.add_argument("--resumen", action="store_true", help="un solo mensaje con toda la watchlist en cada ciclo")
    r.add_argument("--solo-operaciones", action="store_true", help="solo avisa compras y ventas, sin señales ni resumen")
    r.add_argument("--confirmar", action="store_true", help="al terminar, avisa cuántas operaciones hizo")
    r.add_argument("--mercados", default="", help="limita el ciclo, ej: crypto o us,byma")
    sub.add_parser("resumen-dia", help="resumen de cierre del día (no opera)")
    q = sub.add_parser("cotizacion", help="cotización y lectura técnica de un activo")
    q.add_argument("simbolo", nargs="?", default="")
    sub.add_parser("cartera", help="cartera simulada con precios actuales")
    sub.add_parser("panel", help="regenera el panel web (state/panel.html)")
    inf = sub.add_parser("informe", help="informe de análisis en Markdown con prompt para un chat de análisis")
    inf.add_argument("--dias", type=int, default=7)

    d = sub.add_parser("decide")
    d.add_argument("--symbol", required=True)
    d.add_argument("--market", choices=["crypto", "us", "byma"])
    d.add_argument("--side", choices=["buy", "sell"], required=True)
    d.add_argument("--qty", type=float, required=True)
    d.add_argument("--price", type=float)
    d.add_argument("--stop", type=float)
    d.add_argument("--execute-paper", action="store_true")

    b = sub.add_parser("backtest")
    b.add_argument("--symbol", default="BTC/USDT")
    b.add_argument("--market", default="crypto")
    b.add_argument("--timeframe", default="1d")
    b.add_argument("--csv", help="CSV exportado de Investing/TradingView")

    sub.add_parser("status")
    rp = sub.add_parser("reporte")
    rp.add_argument("--dias", type=int, default=7)
    cc = sub.add_parser("ccl", help="muestra el dólar CCL implícito")
    cc.add_argument("--enviar", action="store_true", help="también lo manda por WhatsApp")
    a = p.parse_args()
    cfg = load_cfg(a.config)
    os.makedirs(cfg["state_dir"], exist_ok=True)

    if a.cmd == "scan":
        cycle(cfg, "alerts", a.offline)
    elif a.cmd == "run":
        mode = a.mode or cfg["mode"]
        while True:
            try:
                mk = {m.strip() for m in a.mercados.split(",") if m.strip()} or None
                ops, n = cycle(cfg, mode, a.offline, a.confirm_live, a.resumen, a.solo_operaciones, mk)
                if a.confirmar:
                    notify(f"✅ Ciclo ejecutado: {n} activos analizados, {ops['buy']} compras y {ops['sell']} ventas."
                           + ("" if ops["buy"] or ops["sell"] else " Sin señales nuevas para operar."))
                if mode == "paper":
                    maybe_weekly_report(cfg, a.offline)
            except Exception as e:  # que un error de red no corte el loop
                print(f"[ciclo] error: {e}")
            if not a.loop:
                break
            time.sleep(a.loop)
    elif a.cmd == "decide":
        cmd_decide(cfg, a)
    elif a.cmd == "backtest":
        df = load_csv(a.csv) if a.csv else fetch_ohlcv(a.symbol, a.market, a.timeframe, 1000, a.offline)
        print(bt.report(bt.run(df, cfg["strategy"], cfg["risk"])))
    elif a.cmd == "cotizacion":
        cmd_quote(cfg, a.simbolo, a.offline)
    elif a.cmd == "informe":
        cmd_informe(cfg, a.dias, a.offline)
    elif a.cmd == "panel":
        cmd_panel(cfg, a.offline)
    elif a.cmd == "cartera":
        cmd_portfolio(cfg, a.offline)
    elif a.cmd == "resumen-dia":
        cmd_daily(cfg, a.offline)
    elif a.cmd == "ccl":
        text = "\n".join(ccl_lines(cfg, {}, a.offline)[1:]) or "No se pudo calcular el CCL."
        notify(text) if a.enviar else print(text.replace("<b>", "").replace("</b>", ""))
    elif a.cmd == "reporte":
        a.offline = a.offline
        cmd_report(cfg, a)
    elif a.cmd == "status":
        print(PaperBroker(cfg["state_dir"], cfg["capital"]).summary())


if __name__ == "__main__":
    main()
