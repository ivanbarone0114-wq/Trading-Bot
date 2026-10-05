"""Panel web (HTML autocontenido) con patrimonio, métricas, posiciones, operaciones, señales, CCL y arbitraje."""
import csv, json, os
from datetime import datetime

from .ccl import implied_ccl
from .cedears import arbitrage
from .informe import pair_trades, trade_stats
from .strategy import prepare, trend_of

MKT = {"crypto": "Cripto", "us": "EE.UU.", "byma": "BYMA"}
CUR = {"crypto": "USDT", "us": "USD", "byma": "ARS"}


def record_equity(state_dir, paper, last_px, ccl):
    """Agrega un punto a la curva de patrimonio (cada ciclo)."""
    eq = dict(paper.s["cash"])
    for sym, p in paper.s["positions"].items():
        eq[p["market"]] = eq.get(p["market"], 0.0) + p["qty"] * last_px.get(sym, p["avg"])
    total = eq.get("crypto", 0) + eq.get("us", 0) + (eq.get("byma", 0) / ccl if ccl else 0)
    path = os.path.join(state_dir, "equity_intraday.csv")
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            rows = list(csv.DictReader(f))
    rows.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "crypto": round(eq.get("crypto", 0), 4),
                 "us": round(eq.get("us", 0), 4), "byma": round(eq.get("byma", 0), 2),
                 "ccl": round(ccl, 2) if ccl else "", "total_usd": round(total, 4)})
    rows = rows[-3000:]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, ["time", "crypto", "us", "byma", "ccl", "total_usd"])
        w.writeheader(); w.writerows(rows)
    return eq, total


def _detail(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return None


def write_panel(cfg, paper, journal, results, px_cache, last_px, offline=False):
    """results: lista de (item, sig, df). Escribe state/panel.html."""
    now = datetime.now()
    ccl_rows, ccl = implied_ccl(cfg, px_cache, offline)
    try:
        arb_rows, ref, ref_src, thr = arbitrage(cfg, px_cache, offline)
    except Exception as e:
        print(f"[panel] arbitraje: {e}")
        arb_rows, ref, ref_src, thr = [], ccl, "", 0.03

    with open(journal.path) as f:
        rows = sorted(csv.DictReader(f), key=lambda r: r["time"])
    closed, _ = pair_trades(rows)
    stats = trade_stats(closed)
    last_buy = {}
    ops = []
    for r in rows:
        if r["kind"] != "trade" or r["mode"] != "paper":
            continue
        d = _detail(r.get("detail"))
        if r["side"] == "buy":
            last_buy[r["symbol"]] = d
        ops.append({"t": datetime.fromisoformat(r["time"]).astimezone().strftime("%d/%m %H:%M"),
                    "side": r["side"], "sym": r["symbol"], "mkt": MKT.get(r["market"], r["market"]),
                    "qty": float(r["qty"] or 0), "price": float(r["price"] or 0),
                    "pnl": float(r["pnl"]) if r["pnl"] else None, "note": r["note"], "detail": d})
    ops.reverse()

    # patrimonio
    eq = dict(paper.s["cash"])
    positions = []
    for sym, p in paper.s["positions"].items():
        px = last_px.get(sym, p["avg"])
        eq[p["market"]] = eq.get(p["market"], 0.0) + p["qty"] * px
        stop, target = p.get("stop"), p.get("target")
        prog = (px - stop) / (target - stop) if stop and target and target > stop else None
        positions.append({"sym": sym, "mkt": MKT[p["market"]], "cur": CUR[p["market"]], "qty": p["qty"],
                          "avg": p["avg"], "px": px, "ret": px / p["avg"] - 1, "pnl": (px - p["avg"]) * p["qty"],
                          "stop": stop, "target": target, "progress": prog,
                          "entry_prog": (p["avg"] - stop) / (target - stop) if prog is not None else None,
                          "detail": last_buy.get(sym)})
    cap = cfg["capital"]
    markets = []
    for m in ("crypto", "us", "byma"):
        e = eq.get(m, 0.0)
        markets.append({"key": m, "name": MKT[m], "cur": CUR[m], "capital": cap[m], "equity": e,
                        "ret": e / cap[m] - 1 if cap[m] else None, "cash": paper.s["cash"].get(m, 0.0),
                        "invested": 1 - paper.s["cash"].get(m, 0.0) / e if e else 0})
    to_usd = lambda m, v: v / ccl if m == "byma" and ccl else (0 if m == "byma" else v)
    total_usd = sum(to_usd(m["key"], m["equity"]) for m in markets)
    cap_usd = sum(to_usd(m["key"], m["capital"]) for m in markets)
    realized_usd = sum(to_usd(c["market"], c["pnl"]) for c in closed)

    # curva
    curve = []
    path = os.path.join(cfg["state_dir"], "equity_intraday.csv")
    if os.path.exists(path):
        with open(path) as f:
            curve = [{"t": r["time"], "v": float(r["total_usd"])} for r in csv.DictReader(f) if r["total_usd"]]

    # señales
    trend = {1: "alcista", -1: "bajista", 0: "lateral"}
    sigs = []
    for item, s, df in results:
        try:
            d = prepare(df, cfg["strategy"]).iloc[-1]
            tr, mac = trend[trend_of(d)], "↑" if d["macd_hist"] > 0 else "↓"
        except Exception:
            tr, mac = "—", "—"
        sigs.append({"sym": s.symbol, "mkt": MKT[item["market"]], "action": s.action, "score": s.score,
                     "price": s.price, "rsi": s.rsi, "trend": tr, "macd": mac, "reasons": s.reasons})
    sigs.sort(key=lambda x: -x["score"])

    data = {
        "updated": now.strftime("%d/%m/%Y %H:%M"),
        "kpi": {"total_usd": total_usd, "cap_usd": cap_usd, "ret": total_usd / cap_usd - 1 if cap_usd else None,
                "realized_usd": realized_usd, "n_closed": len(closed), "n_open": len(positions),
                "win_rate": stats["win_rate"] if stats else None, "pf": stats["pf"] if stats else None,
                "expectancy": stats["expectancy"] if stats else None, "ccl": ccl},
        "markets": markets, "curve": curve,
        "closed": [{"sym": c["symbol"], "ret": c["ret"], "pnl": c["pnl"], "why": c["why"],
                    "t_out": c["t_out"].strftime("%d/%m %H:%M")} for c in closed],
        "positions": positions, "ops": ops[:300], "signals": sigs,
        "ccl_pairs": [{"via": n, "v": v, "note": note} for n, v, note in ccl_rows],
        "arb": arb_rows, "arb_ref": ref, "arb_ref_src": ref_src, "arb_thr": thr,
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/"))
    out = os.path.join(cfg["state_dir"], "panel.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Panel · Trading bot</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#E9EDF1;--surface:#fff;--surface-2:#F3F5F8;--ink:#14202C;--muted:#5A6877;--line:#D5DCE3;
--bull:#0B8A68;--bear:#C23B34;--hold:#8A6A12;--accent:#2742C9;--bull-soft:rgba(11,138,104,.12);--bear-soft:rgba(194,59,52,.12);
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0E151D;--surface:#16202B;--surface-2:#1C2835;--ink:#E4EBF2;--muted:#8FA0B1;--line:#273545;
--bull:#37C29A;--bear:#EE6E63;--hold:#D9B04A;--accent:#8CA0FF;--bull-soft:rgba(55,194,154,.14);--bear-soft:rgba(238,110,99,.14);color-scheme:dark}}
*,*::before,*::after{box-sizing:inherit}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Archivo",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.45;font-variant-numeric:tabular-nums}
.wrap{max-width:820px;margin:0 auto;padding:14px 14px calc(84px + env(safe-area-inset-bottom,0px))}
header{display:flex;flex-direction:column;gap:4px;margin:4px 0 14px}
header h1{display:flex;align-items:center;gap:8px;font-size:20px;font-stretch:115%;margin:0;font-weight:800}
.badge{font-size:12px;font-weight:700;padding:3px 8px;border-radius:999px;background:var(--surface-2);border:1px solid var(--line);color:var(--muted)}
.upd{font-size:12px;color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:12px}
.card h2{font-size:15px;margin:0 0 10px;font-stretch:108%}
.hero .big{font-size:clamp(30px,9vw,48px);font-weight:800;font-stretch:118%;line-height:1;margin:2px 0 6px}
.k{font-size:12px;color:var(--muted)} .v{font-size:18px;font-weight:700;font-stretch:106%}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
@media (min-width:600px){.grid{grid-template-columns:repeat(4,1fr)}}
.pos{color:var(--bull)} .neg{color:var(--bear)}
.chart{position:relative;height:220px}
.row{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.list{list-style:none;margin:0;padding:0} .list>li{padding:12px 0;border-top:1px solid var(--line)} .list>li:first-child{border-top:0}
.sub{font-size:13px;color:var(--muted)}
.bar{position:relative;height:10px;border-radius:5px;margin:12px 0 6px;background:linear-gradient(90deg,var(--bear-soft),var(--surface-2) 50%,var(--bull-soft));border:1px solid var(--line)}
.bar i{position:absolute;top:-4px;width:3px;height:16px;border-radius:2px}
.bar .cur{background:var(--ink)} .bar .ent{background:var(--muted);opacity:.6}
.bar-l{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
details{margin-top:8px} summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:14px}
.why{margin-top:8px;font-size:14px}
.why h4{margin:8px 0 4px;font-size:13px} .why ul{margin:0;padding-left:18px}
.why .p h4{color:var(--bull)} .why .c h4{color:var(--bear)}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px}
.tag.BUY,.tag.buy,.tag.cheap{background:var(--bull-soft);color:var(--bull)}
.tag.SELL,.tag.sell,.tag.rich{background:var(--bear-soft);color:var(--bear)}
.tag.HOLD,.tag.ok,.tag.stale,.tag.check{background:var(--surface-2);color:var(--muted)}
.tbl{overflow-x:auto} table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}
th,td{padding:7px 8px;border-top:1px solid var(--line);text-align:right} th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:600}
.seg{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.seg button{border:1px solid var(--line);background:var(--surface-2);color:var(--ink);border-radius:8px;padding:6px 10px;font:inherit;font-size:13px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--surface)}
nav{position:fixed;left:0;right:0;bottom:0;background:var(--surface);border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom,0px);z-index:5}
nav .in{display:flex;max-width:820px;margin:0 auto}
nav button{flex:1;border:0;background:none;color:var(--muted);font:inherit;font-size:12px;font-weight:600;padding:11px 2px 13px;border-top:3px solid transparent;cursor:pointer}
nav button[aria-selected=true]{color:var(--ink);border-top-color:var(--accent)}
section{display:none} section.on{display:block}
.empty{color:var(--muted);text-align:center;padding:18px 6px}
.note{font-size:12px;color:var(--muted);margin-top:8px}
</style></head><body>
<div class="wrap">
<header><h1>Trading bot <span class="badge">PAPER</span></h1><span class="upd" id="upd"></span></header>

<section id="t-res" class="on">
  <div class="card hero"><div class="k">Patrimonio total (USD, BYMA al CCL)</div><div class="big" id="total"></div><div id="totsub" class="sub"></div></div>
  <div class="card"><div class="grid" id="kpis"></div></div>
  <div class="card"><h2>Curva de patrimonio</h2><div class="chart"><canvas id="cEq"></canvas></div><p class="note" id="eqnote"></p></div>
  <div class="card"><h2>Resultado por operación</h2><div class="chart"><canvas id="cHist"></canvas></div><p class="note">Cada barra cuenta operaciones cerradas en ese rango de resultado. Rojo: pérdidas. Azul: ganancias.</p></div>
  <div class="card"><h2>Por mercado</h2><ul class="list" id="mkts"></ul></div>
</section>

<section id="t-pos"><div class="card"><h2>Posiciones abiertas</h2><ul class="list" id="poslist"></ul></div></section>

<section id="t-ops"><div class="card"><h2>Operaciones y por qué</h2><ul class="list" id="opslist"></ul></div></section>

<section id="t-sig"><div class="card"><h2>Ranking de señales</h2>
  <div class="seg" id="sigf"><button data-f="all" aria-pressed="true">Todos</button><button data-f="Cripto" aria-pressed="false">Cripto</button><button data-f="EE.UU." aria-pressed="false">EE.UU.</button><button data-f="BYMA" aria-pressed="false">BYMA</button></div>
  <div class="tbl"><table><thead><tr><th>Activo</th><th>Señal</th><th>Score</th><th>Precio</th><th>RSI</th><th>MACD</th><th>Tendencia</th></tr></thead><tbody id="sigtb"></tbody></table></div></div></section>

<section id="t-ccl">
  <div class="card"><h2>Dólar CCL implícito</h2><div class="grid" id="cclg"></div></div>
  <div class="card"><h2>CEDEARs vs CCL</h2><p class="sub" id="arbinfo"></p><ul class="list" id="arblist"></ul>
  <p class="note">CCL implícito = precio del CEDEAR en pesos × ratio ÷ precio de la acción en dólares. Si es más bajo que el CCL de referencia, el CEDEAR está "barato" en dólares. Los precios tienen demora y no incluyen comisiones ni spreads: un desvío chico no alcanza para arbitrar. Verificá los ratios en la tabla oficial del programa CEDEAR.</p></div>
</section>
<p class="note" style="text-align:center">Paper trading: dinero simulado. No es asesoramiento financiero. DYOR.</p>
</div>
<nav><div class="in">
<button data-t="t-res" aria-selected="true">Resumen</button><button data-t="t-pos" aria-selected="false">Posiciones</button>
<button data-t="t-ops" aria-selected="false">Operaciones</button><button data-t="t-sig" aria-selected="false">Señales</button>
<button data-t="t-ccl" aria-selected="false">CCL</button></div></nav>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const nf = (x, d = 2) => x == null || isNaN(x) ? '—' : Number(x).toLocaleString('es-AR', {minimumFractionDigits: d, maximumFractionDigits: d});
const px = x => x == null ? '—' : nf(x, Math.abs(x) < 1 ? 4 : 2);
const pc = (x, d = 1) => x == null || isNaN(x) ? '—' : (x > 0 ? '+' : '') + nf(x * 100, d) + '%';
const cls = x => x > 0 ? 'pos' : x < 0 ? 'neg' : '';
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('section').forEach(s => s.classList.toggle('on', s.id === b.dataset.t));
  window.scrollTo(0, 0);
});
$('#upd').textContent = 'Actualizado ' + D.updated;

// ---- resumen
const K = D.kpi;
$('#total').textContent = 'US$ ' + nf(K.total_usd);
$('#totsub').innerHTML = `<span class="${cls(K.ret)}">${pc(K.ret, 2)}</span> sobre un capital de US$ ${nf(K.cap_usd)}`;
$('#kpis').innerHTML = [
  ['Ganancia realizada', `<span class="${cls(K.realized_usd)}">US$ ${nf(K.realized_usd)}</span>`],
  ['Acierto', K.win_rate == null ? '—' : nf(K.win_rate * 100, 0) + '%'],
  ['Profit factor', K.pf == null ? '—' : nf(K.pf)],
  ['Expectativa / operación', pc(K.expectancy, 2)],
  ['Operaciones cerradas', K.n_closed], ['Posiciones abiertas', K.n_open],
  ['CCL de referencia', K.ccl ? '$ ' + nf(K.ccl) : '—'], ['Señales analizadas', D.signals.length],
].map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
$('#mkts').innerHTML = D.markets.map(m => `<li><div class="row"><b>${m.name}</b><span class="${cls(m.ret)}">${pc(m.ret, 2)}</span></div>
  <div class="sub">Patrimonio ${nf(m.equity)} ${m.cur} · capital ${nf(m.capital, 0)} · efectivo ${nf(m.cash)} · invertido ${nf(m.invested * 100, 0)}%</div></li>`).join('');

if (window.Chart) {
  Chart.defaults.color = css('--muted'); Chart.defaults.font.family = 'Archivo, system-ui, sans-serif';
  const grid = {color: css('--line') + '88'};
  if (D.curve.length > 1) {
    new Chart($('#cEq'), {type: 'line', data: {labels: D.curve.map(p => p.t.slice(5)),
      datasets: [{data: D.curve.map(p => p.v), borderColor: css('--accent'), backgroundColor: css('--accent') + '22', fill: true, pointRadius: 0, tension: .25, borderWidth: 2}]},
      options: {maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {x: {grid, ticks: {maxTicksLimit: 6}}, y: {grid}}}});
    $('#eqnote').textContent = `${D.curve.length} registros, uno por ciclo del bot.`;
  } else { $('#cEq').parentElement.innerHTML = '<p class="empty">La curva aparece después de algunos ciclos del bot.</p>'; }
  const rets = D.closed.map(c => c.ret).filter(r => r != null);
  if (rets.length) {
    const lo = Math.floor(Math.min(...rets, 0) * 100), hi = Math.ceil(Math.max(...rets, 0) * 100);
    const step = Math.max(1, Math.ceil((hi - lo) / 14)), bins = [];
    for (let b = lo; b < hi || bins.length === 0; b += step) bins.push(b);
    const counts = bins.map(b => rets.filter(r => r * 100 >= b && r * 100 < b + step).length);
    new Chart($('#cHist'), {type: 'bar', data: {labels: bins.map(b => `${b}%`),
      datasets: [{data: counts, backgroundColor: bins.map(b => b + step / 2 < 0 ? css('--bear') : css('--accent')), borderRadius: 4}]},
      options: {maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {x: {grid: {display: false}}, y: {grid, ticks: {precision: 0}}}}});
  } else { $('#cHist').parentElement.innerHTML = '<p class="empty">Todavía no hay operaciones cerradas.</p>'; }
}

// ---- justificación
const why = d => !d ? '<p class="sub">Sin detalle registrado (operación anterior a esta versión).</p>' :
  `<div class="why"><p>${esc(d.resumen)}</p>
   <div class="p"><h4>Lo que la justifica</h4><ul>${(d.pro || []).map(x => `<li>${esc(x)}</li>`).join('') || '<li>—</li>'}</ul></div>
   <div class="c"><h4>Lo que la refuta</h4><ul>${(d.contra || []).map(x => `<li>${esc(x)}</li>`).join('') || '<li>Sin objeciones relevantes</li>'}</ul></div></div>`;

// ---- posiciones
$('#poslist').innerHTML = D.positions.length ? D.positions.map(p => {
  const clamp = x => Math.max(0, Math.min(1, x)) * 100;
  const bar = p.progress == null ? '' : `<div class="bar"><i class="ent" style="left:${clamp(p.entry_prog)}%"></i><i class="cur" style="left:${clamp(p.progress)}%"></i></div>
    <div class="bar-l"><span>Stop ${px(p.stop)}</span><span>Objetivo ${px(p.target)}</span></div>`;
  return `<li><div class="row"><b>${esc(p.sym)} <span class="sub">${p.mkt}</span></b><span class="${cls(p.ret)}">${pc(p.ret, 2)}</span></div>
    <div class="sub">${nf(p.qty, 4)} a ${px(p.avg)} → ${px(p.px)} ${p.cur} · resultado ${nf(p.pnl)} ${p.cur}</div>${bar}
    <details><summary>Por qué se compró</summary>${why(p.detail)}</details></li>`;
}).join('') : '<li class="empty">No hay posiciones abiertas.</li>';

// ---- operaciones
$('#opslist').innerHTML = D.ops.length ? D.ops.map(o => `<li><div class="row"><span><span class="tag ${o.side}">${o.side === 'buy' ? 'COMPRA' : 'VENTA'}</span> <b>${esc(o.sym)}</b> <span class="sub">${o.mkt}</span></span>
  ${o.pnl == null ? '' : `<span class="${cls(o.pnl)}">${o.pnl > 0 ? '+' : ''}${nf(o.pnl)}</span>`}</div>
  <div class="sub">${o.t} · ${nf(o.qty, 4)} a ${px(o.price)} · ${esc(o.note)}</div>
  <details><summary>Justificación y refutación</summary>${why(o.detail)}</details></li>`).join('') : '<li class="empty">Todavía no hubo operaciones.</li>';

// ---- señales
const drawSig = f => { $('#sigtb').innerHTML = D.signals.filter(s => f === 'all' || s.mkt === f).map(s =>
  `<tr><td><b>${esc(s.sym)}</b></td><td><span class="tag ${s.action}">${s.action}</span></td><td class="${cls(s.score)}">${s.score > 0 ? '+' : ''}${nf(s.score)}</td>
   <td>${px(s.price)}</td><td>${nf(s.rsi, 0)}</td><td>${s.macd}</td><td>${s.trend}</td></tr>`).join(''); };
document.querySelectorAll('#sigf button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#sigf button').forEach(x => x.setAttribute('aria-pressed', x === b)); drawSig(b.dataset.f); });
drawSig('all');

// ---- CCL y arbitraje
$('#cclg').innerHTML = D.ccl_pairs.map(c => `<div><div class="k">Vía ${esc(c.via)}</div><div class="v">$ ${nf(c.v)}</div><div class="sub">${esc(c.note)}</div></div>`).join('')
  + (K.ccl ? `<div><div class="k">Referencia</div><div class="v">$ ${nf(K.ccl)}</div></div>` : '') || '<p class="empty">Sin datos de CCL.</p>';
$('#arbinfo').textContent = D.arb.length ? `CCL de referencia ${D.arb_ref ? '$ ' + nf(D.arb_ref) : '—'} (${D.arb_ref_src}). Se marca desvío a partir de ±${nf(D.arb_thr * 100, 1)}%.` : '';
const order = {cheap: 0, rich: 1, check: 2, stale: 3, ok: 4};
$('#arblist').innerHTML = D.arb.length ? D.arb.slice().sort((a, b) => order[a.kind] - order[b.kind] || Math.abs(b.dev) - Math.abs(a.dev)).map(a =>
  `<li><div class="row"><b>${esc(a.symbol)}</b><span class="${a.kind === 'cheap' ? 'pos' : a.kind === 'rich' ? 'neg' : ''}">${pc(a.dev, 2)}</span></div>
   <div class="sub">CEDEAR $ ${nf(a.ars)} · acción US$ ${px(a.usd)} · ratio ${nf(a.ratio, 0)} · CCL implícito $ ${nf(a.ccl)}</div>
   <div style="margin-top:6px"><span class="tag ${a.kind}">${esc(a.read)}</span></div></li>`).join('')
  : '<li class="empty">No hay CEDEARs configurados. Agregá la sección cedears en config.yaml.</li>';
</script></body></html>"""
