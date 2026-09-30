"""CLI del bot.
  python -m bot.main scan                 → alertas (sin operar)
  python -m bot.main run [--loop 3600]    → ciclo según 'mode' del config (alerts/paper/live)
  python -m bot.main decide ...           → registrás tu decisión y recibís consejos
  python -m bot.main backtest ...         → prueba histórica
  python -m bot.main status               → cartera simulada
Agregá --offline para probar con datos sintéticos."""
import argparse, json, os, sys, time
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
from .ccl import ccl_lines


def load_cfg(path):
    with open(path) as f:
        return yaml.safe_load(f)


def analyze(item, cfg, offline):
    df = fetch_ohlcv(item["symbol"], item["market"], item["timeframe"], 500, offline)
    df_htf = fetch_ohlcv(item["symbol"], item["market"], item["htf"], 200, offline) if item.get("htf") else None
    ns, titles = (None, [])
    if cfg["news"]["enabled"] and not offline:
        ns, titles = news_sentiment(item.get("keywords"), cfg["news"]["max_items"])
    label = item["symbol"] + ".BA" if item["market"] == "byma" and not item["symbol"].endswith(".BA") else item["symbol"]
    sig = evaluate(df, cfg["strategy"], label, ns, df_htf)
    return sig, df, titles


def get_brokers(cfg, mode, confirm_live):
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
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


def cycle(cfg, mode, offline, confirm_live=False, summary=False, quiet=False):
    j = Journal(cfg["state_dir"])
    risk = RiskManager(cfg["risk"], cfg["capital"], cfg["state_dir"])
    brokers = get_brokers(cfg, mode, confirm_live) if mode in ("paper", "live") else None
    lines, last_px, px_cache = [], {}, {}

    for item in cfg["watchlist"]:
        mkt = item["market"]
        try:
            sig, df, _ = analyze(item, cfg, offline)
            sym = sig.symbol
            px_cache[sym] = (float(df["close"].iloc[-1]), df.index[-1].date())
        except Exception as e:
            print(f"[{item['symbol']}] error de datos: {e}")
            continue

        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[sig.action]
        lines.append(f"{emoji} <b>{sym}</b> {sig.action} ({sig.score:+.2f}) | {sig.price:,.2f} | RSI {sig.rsi:.0f}")
        if sig.action != "HOLD" and not alerted_before(cfg["state_dir"], sig):
            if not summary and not quiet:
                notify(sig.text())
            j.log(kind="alert", mode=mode, symbol=sym, market=mkt, side=sig.action, price=sig.price,
                  stop=sig.stop or "", target=sig.target or "", note=f"score {sig.score}")
        if not brokers:
            continue

        b = brokers[mkt]
        pos = b.position(sym)
        last = df.iloc[-1]
        last_px[sym] = float(last["close"])

        if pos and pos["qty"] > 0:
            why = None
            if pos.get("stop") and last["low"] <= pos["stop"]:
                why, px = "stop", pos["stop"]
            elif pos.get("target") and last["high"] >= pos["target"]:
                why, px = "objetivo", pos["target"]
            elif sig.action == "SELL":
                why, px = "señal", sig.price
            if why and confirm(f"[{mode}] VENDER {pos['qty']:.6f} {sym} @ {px:,.4f} ({why}).", cfg, mode):
                pnl, fill = b.sell(sym, mkt, pos["qty"], px)
                j.log(kind="trade", mode=mode, symbol=sym, market=mkt, side="sell", qty=pos["qty"],
                      price=fill, pnl=pnl if pnl is not None else "", note=why)
                notify(f"🔴 [{mode}] Venta {sym} @ {fill:,.4f} ({why})" + (f" | PnL {pnl:+,.2f}" if pnl is not None else ""))

        elif sig.action == "BUY":
            ok, reason = risk.can_open(mkt, b.open_count(mkt), j.realized_today(mkt))
            if not ok:
                print(f"[{sym}] compra bloqueada: {reason}")
                continue
            qty = risk.size(mkt, sig.price, sig.stop, b.cash(mkt))
            if qty <= 0:
                continue
            if confirm(f"[{mode}] COMPRAR {qty:.6f} {sym} @ ~{sig.price:,.4f} (stop {sig.stop:,.4f}).", cfg, mode):
                fill = b.buy(sym, mkt, qty, sig.price, sig.stop, sig.target)
                j.log(kind="trade", mode=mode, symbol=sym, market=mkt, side="buy", qty=qty, price=fill,
                      stop=sig.stop, target=sig.target, note=f"score {sig.score}")
                notify(f"🟢 [{mode}] Compra {qty:.6f} {sym} @ {fill:,.4f} | stop {sig.stop:,.4f} | obj {sig.target:,.4f}")

    if summary and lines:
        from datetime import datetime
        extra = paper_lines(brokers["crypto"], last_px, j) if mode == "paper" and brokers else []
        if cfg.get("ccl", {}).get("enabled", True):
            extra = ccl_lines(cfg, px_cache, offline) + extra
        notify(f"📊 <b>Resumen {datetime.now():%d/%m %H:%M}</b>\n" + "\n".join(lines + extra) + "\n⚠️ No es consejo financiero. DYOR.")


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


def cmd_daily(cfg, offline=False):
    """Resumen de cierre: señales, operaciones del día, CCL y cartera. No opera."""
    from datetime import datetime
    j = Journal(cfg["state_dir"])
    paper = PaperBroker(cfg["state_dir"], cfg["capital"], cfg["risk"]["fee"], cfg["risk"]["slippage"])
    lines, px_cache, last_px = [], {}, {}
    for item in cfg["watchlist"]:
        try:
            sig, df, _ = analyze(item, cfg, offline)
        except Exception as e:
            print(f"[{item['symbol']}] error de datos: {e}")
            continue
        px = float(df["close"].iloc[-1])
        px_cache[sig.symbol] = (px, df.index[-1].date())
        last_px[sig.symbol] = px
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[sig.action]
        lines.append(f"{emoji} <b>{sig.symbol}</b> {sig.action} ({sig.score:+.2f}) | {px:,.2f} | RSI {sig.rsi:.0f}")

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
    extra += paper_lines(paper, last_px, j)
    notify(f"🌙 <b>Resumen del día {datetime.now():%d/%m}</b>\n" + "\n".join(lines + extra)
           + "\n⚠️ No es consejo financiero. DYOR.")


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
    lines += paper_lines(paper, {}, j)[1:]
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
    sub.add_parser("resumen-dia", help="resumen de cierre del día (no opera)")

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
                cycle(cfg, mode, a.offline, a.confirm_live, a.resumen, a.solo_operaciones)
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
