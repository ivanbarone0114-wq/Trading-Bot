"""Descarga de velas OHLCV: cripto (ccxt/Binance), EE.UU. y BYMA (yfinance)."""
import os
import zlib
import numpy as np
import pandas as pd

YF_INTERVAL = {"5m": ("5m", "30d"), "15m": ("15m", "60d"), "30m": ("30m", "60d"), "1h": ("1h", "730d"), "4h": ("1h", "730d"), "1d": ("1d", "5y"), "1wk": ("1wk", "10y")}
COLS = ["open", "high", "low", "close", "volume"]


def yf_symbol(symbol: str, market: str) -> str:
    if market == "byma" and not symbol.endswith(".BA"):
        return symbol + ".BA"
    return symbol


def fetch_ohlcv(symbol, market, timeframe="1d", limit=500, offline=False):
    if offline or market == "synthetic":
        return synthetic_ohlcv(n=limit, seed=zlib.crc32(f"{symbol}{timeframe}".encode()))

    if market == "crypto":
        # Binance bloquea servidores de EE.UU. (como los de GitHub): se prueba en orden y, si todo falla, Yahoo.
        import ccxt
        for ex_id in os.getenv("CRYPTO_SOURCES", "binance,kraken").split(","):
            try:
                ex = getattr(ccxt, ex_id.strip())({"enableRateLimit": True})
                raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                if raw:
                    df = pd.DataFrame(raw, columns=["ts"] + COLS)
                    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
                    return df.set_index("ts").astype(float).dropna()
            except Exception as e:
                print(f"[{symbol}] {ex_id} no disponible ({e.__class__.__name__}), probando otra fuente")
        return fetch_ohlcv(symbol.split("/")[0] + "-USD", "us", timeframe, limit)

    if market in ("us", "byma"):
        import yfinance as yf
        interval, period = YF_INTERVAL[timeframe]
        df = yf.download(yf_symbol(symbol, market), interval=interval, period=period,
                         auto_adjust=True, progress=False)
        if df.empty:
            raise ValueError(f"Sin datos para {symbol} ({market})")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns=str.lower)[COLS].astype(float)
        df = df.dropna(subset=["open", "high", "low", "close"])
        if timeframe == "4h":
            df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                        "close": "last", "volume": "sum"}).dropna()
        return df.tail(limit)

    raise ValueError(f"Mercado desconocido: {market}")


def load_csv(path):
    """CSV exportado de Investing/TradingView. Acepta columnas en español o inglés."""
    df = pd.read_csv(path)
    ren = {"fecha": "date", "apertura": "open", "máximo": "high", "maximo": "high",
           "mínimo": "low", "minimo": "low", "último": "close", "ultimo": "close",
           "cierre": "close", "vol.": "volume", "volumen": "volume", "time": "date"}
    df.columns = [ren.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date").sort_index()
    for c in ["open", "high", "low", "close"]:
        if df[c].dtype == object:  # formato 1.234,56
            df[c] = df[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False).astype(float)
    if "volume" not in df:
        df["volume"] = 0.0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    return df[COLS]


def synthetic_ohlcv(n=500, seed=0, start=100.0):
    """Datos sintéticos con regímenes de tendencia, para probar sin internet."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.003, n // 60 + 1), 60)[:n]
    close = start * np.exp(np.cumsum(drift + rng.normal(0, 0.015, n)))
    open_ = np.r_[start, close[:-1]] * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(1000, 5000, n).astype(float)}, index=idx)
