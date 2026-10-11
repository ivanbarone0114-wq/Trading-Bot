"""Registro de mercados. Cripto tiene dos estrategias con capital separado:
crypto_d = trading diario (velas de 1 h, cierre máximo a las 24 h)
crypto_t = seguimiento de tendencia (velas diarias, operaciones de semanas)
"crypto" es el mercado anterior; se mantiene solo para leer la bitácora vieja."""
import re

MKT = {"crypto_d": "Cripto diario", "crypto_t": "Cripto tendencia", "crypto": "Cripto (anterior)",
       "us": "EE.UU.", "byma": "BYMA"}
CUR = {"crypto_d": "USDT", "crypto_t": "USDT", "crypto": "USDT", "us": "USD", "byma": "ARS"}
ACTIVE = ("crypto_d", "crypto_t", "us", "byma")
CRYPTO_STRATS = ("crypto_d", "crypto_t")
SUFFIX = {"crypto_d": " [D]", "crypto_t": " [T]"}


def is_crypto(market):
    return str(market).startswith("crypto")


def base_market(market):
    return "crypto" if is_crypto(market) else market


def label_for(symbol, market):
    if market == "byma" and not symbol.endswith(".BA"):
        return symbol + ".BA"
    return symbol + SUFFIX.get(market, "")


def base_symbol(label):
    s = re.sub(r" \[[DT]\]$", "", label)
    return s[:-3] if s.endswith(".BA") else s
