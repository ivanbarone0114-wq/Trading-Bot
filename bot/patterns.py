"""Patrones de velas japonesas (vectorizados). +1 alcista, -1 bajista."""
import numpy as np
import pandas as pd

BULL = ["martillo", "envolvente_alcista", "estrella_manana"]
BEAR = ["estrella_fugaz", "envolvente_bajista", "estrella_atardecer"]


def detect(df):
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = c - o
    ab = body.abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    downtrend = c < c.shift(5)
    uptrend = c > c.shift(5)
    mid2 = (o.shift(2) + c.shift(2)) / 2

    p = pd.DataFrame(index=df.index)
    p["martillo"] = (lower >= 2 * ab) & (upper <= 0.25 * rng) & downtrend
    p["estrella_fugaz"] = (upper >= 2 * ab) & (lower <= 0.25 * rng) & uptrend
    p["envolvente_alcista"] = (c.shift(1) < o.shift(1)) & (c > o) & (o <= c.shift(1)) & (c >= o.shift(1)) & downtrend.shift(1, fill_value=False)
    p["envolvente_bajista"] = (c.shift(1) > o.shift(1)) & (c < o) & (o >= c.shift(1)) & (c <= o.shift(1)) & uptrend.shift(1, fill_value=False)
    p["estrella_manana"] = (body.shift(2) < 0) & (ab.shift(2) > 0.6 * rng.shift(2)) & (ab.shift(1) < 0.3 * rng.shift(1)) & (body > 0) & (c > mid2)
    p["estrella_atardecer"] = (body.shift(2) > 0) & (ab.shift(2) > 0.6 * rng.shift(2)) & (ab.shift(1) < 0.3 * rng.shift(1)) & (body < 0) & (c < mid2)
    p["doji"] = ab <= 0.1 * rng
    return p.fillna(False).astype(bool)


def add_patterns(df):
    df = df.copy()
    p = detect(df)
    score = p[BULL].sum(axis=1) - p[BEAR].sum(axis=1)
    df["pattern_score"] = score.clip(-1, 1).astype(float)
    df["patterns"] = p.apply(lambda r: ",".join(k for k, v in r.items() if v), axis=1)
    return df
