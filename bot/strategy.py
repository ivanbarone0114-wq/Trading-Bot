"""Motor de señales: tendencia (EMAs) + MACD + RSI + velas + noticias, con filtro multi-timeframe."""
from dataclasses import dataclass, field
import numpy as np
from .indicators import add_indicators
from .patterns import add_patterns


@dataclass
class Signal:
    symbol: str
    action: str            # BUY | SELL | HOLD
    score: float           # [-1, 1]
    price: float
    stop: float | None
    target: float | None
    rsi: float
    atr: float
    patterns: str
    reasons: list = field(default_factory=list)
    bar_time: str = ""

    def text(self):
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}[self.action]
        lines = [f"{emoji} <b>{self.symbol}</b> → {self.action} (score {self.score:+.2f})",
                 f"Precio: {self.price:,.4f} | RSI: {self.rsi:.1f} | ATR: {self.atr:,.4f}"]
        if self.action == "BUY":
            lines.append(f"Stop: {self.stop:,.4f} | Objetivo: {self.target:,.4f}")
        lines += [f"• {r}" for r in self.reasons]
        lines.append("⚠️ No es consejo financiero. DYOR.")
        return "\n".join(lines)


def prepare(df, cfg):
    return add_patterns(add_indicators(df, cfg))


def trend_of(row):
    if row["close"] > row["ema_slow"] and row["ema_fast"] > row["ema_slow"]:
        return 1
    if row["close"] < row["ema_slow"] and row["ema_fast"] < row["ema_slow"]:
        return -1
    return 0


def htf_trend(df_htf, cfg):
    if df_htf is None or len(df_htf) < cfg["ema_slow"]:
        return 0
    return trend_of(add_indicators(df_htf, cfg).iloc[-1])


def evaluate_row(df, i, cfg, symbol="", news_score=None, htf=0):
    row = df.iloc[i]
    w = cfg["weights"]
    comp, reasons = {}, []

    comp["trend"] = trend_of(row)
    reasons.append({1: "Tendencia alcista (precio y EMA rápida sobre EMA lenta)",
                    -1: "Tendencia bajista (precio y EMA rápida bajo EMA lenta)",
                    0: "Tendencia lateral / sin definición"}[comp["trend"]])

    r = row["rsi"]
    comp["rsi"] = 1 if r < cfg["rsi_oversold"] else -1 if r > cfg["rsi_overbought"] else 0
    if comp["rsi"]:
        reasons.append(f"RSI {r:.0f}: {'sobreventa' if comp['rsi'] > 0 else 'sobrecompra'}")

    hist = df["macd_hist"].iloc[max(0, i - 3): i + 1].values
    cross_up = any(hist[k - 1] <= 0 < hist[k] for k in range(1, len(hist)))
    cross_dn = any(hist[k - 1] >= 0 > hist[k] for k in range(1, len(hist)))
    if cross_up and not cross_dn:
        comp["macd"] = 1; reasons.append("Cruce alcista de MACD reciente")
    elif cross_dn and not cross_up:
        comp["macd"] = -1; reasons.append("Cruce bajista de MACD reciente")
    else:
        comp["macd"] = 0.5 * np.sign(row["macd_hist"])

    comp["patterns"] = row["pattern_score"]
    if row["patterns"]:
        reasons.append(f"Velas: {row['patterns'].replace('_', ' ')}")

    weights = {k: w[k] for k in ("trend", "rsi", "macd", "patterns")}
    if news_score is not None:
        comp["news"] = news_score
        weights["news"] = w["news"]
        reasons.append(f"Noticias: sentimiento {news_score:+.2f}")

    score = sum(weights[k] * comp[k] for k in weights) / sum(weights.values())

    if htf and np.sign(score) and np.sign(score) != htf:
        score *= 0.5
        reasons.append("Temporalidad mayor en contra → señal atenuada")

    th = cfg["threshold"]
    action = "BUY" if score >= th else "SELL" if score <= -th else "HOLD"
    price, a = float(row["close"]), float(row["atr"])
    dist = cfg["atr_stop_mult"] * a
    stop = price - dist if action == "BUY" else None
    target = price + cfg["reward_risk"] * dist if action == "BUY" else None

    return Signal(symbol, action, round(float(score), 3), price, stop, target, float(r), a,
                  row["patterns"], reasons, str(df.index[i]))


def evaluate(df, cfg, symbol="", news_score=None, df_htf=None):
    d = prepare(df, cfg)
    return evaluate_row(d, len(d) - 1, cfg, symbol, news_score, htf_trend(df_htf, cfg))
