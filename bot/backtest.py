"""Backtest long-only: señal al cierre de la vela i, ejecución a la apertura de i+1, stops intravela."""
import numpy as np
from .strategy import prepare, evaluate_row


def run(df, strat_cfg, risk_cfg, capital=10_000.0):
    d = prepare(df, strat_cfg)
    warm = strat_cfg["ema_slow"] + 5
    sigs = {i: evaluate_row(d, i, strat_cfg) for i in range(warm, len(d))}
    fee = risk_cfg["fee"] + risk_cfg["slippage"]
    cash, pos, trades, curve = capital, None, [], []

    def close(i, px, why):
        nonlocal cash, pos
        proceeds = pos["qty"] * px * (1 - fee)
        pnl = proceeds - pos["cost"]
        cash += proceeds
        trades.append({"entry_time": pos["time"], "exit_time": str(d.index[i]), "entry": pos["entry"],
                       "exit": px, "pnl": pnl, "ret": pnl / pos["cost"], "why": why})
        pos = None

    for i in range(warm + 1, len(d)):
        bar, prev = d.iloc[i], sigs[i - 1]
        if pos and prev.action == "SELL":
            close(i, bar["open"], "señal")
        elif not pos and prev.action == "BUY":
            dist = prev.price - prev.stop
            entry = bar["open"]
            equity = cash
            qty = min(equity * risk_cfg["risk_per_trade"] / dist, equity * risk_cfg["max_position_pct"] / entry)
            cost = qty * entry * (1 + fee)
            if qty > 0 and cost <= cash:
                cash -= cost
                pos = {"qty": qty, "entry": entry, "cost": cost, "stop": entry - dist,
                       "target": entry + strat_cfg["reward_risk"] * dist, "time": str(d.index[i])}
        if pos:
            if bar["low"] <= pos["stop"]:
                close(i, min(bar["open"], pos["stop"]), "stop")
            elif bar["high"] >= pos["target"]:
                close(i, max(bar["open"], pos["target"]), "objetivo")
        curve.append(cash + (pos["qty"] * bar["close"] if pos else 0.0))

    if pos:
        close(len(d) - 1, d["close"].iloc[-1], "fin")
        curve[-1] = cash
    curve = np.array(curve)
    peak = np.maximum.accumulate(curve)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_loss = -sum(t["pnl"] for t in losses)
    return {
        "operaciones": len(trades),
        "tasa_acierto": len(wins) / len(trades) if trades else 0.0,
        "retorno_total": curve[-1] / capital - 1 if len(curve) else 0.0,
        "buy_and_hold": d["close"].iloc[-1] / d["close"].iloc[warm + 1] - 1,
        "max_drawdown": float(((curve - peak) / peak).min()) if len(curve) else 0.0,
        "profit_factor": (sum(t["pnl"] for t in wins) / gross_loss) if gross_loss > 0 else float("inf"),
        "trades": trades,
    }


def report(res):
    pf = res["profit_factor"]
    return "\n".join([
        "== Backtest ==",
        f"Operaciones:     {res['operaciones']}",
        f"Tasa de acierto: {res['tasa_acierto']:.1%}",
        f"Retorno total:   {res['retorno_total']:+.2%}",
        f"Buy & hold:      {res['buy_and_hold']:+.2%}  (referencia; el bot arriesga 1% por trade)",
        f"Max drawdown:    {res['max_drawdown']:.2%}",
        f"Profit factor:   {'∞' if pf == float('inf') else f'{pf:.2f}'}",
        "Resultados pasados no garantizan resultados futuros.",
    ])
