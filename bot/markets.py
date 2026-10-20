"""Registro de mercados. Cripto tiene dos estrategias con capital separado:
crypto_d = trading diario (velas de 1 h, cierre máximo a las 24 h)
crypto_t = seguimiento de tendencia (velas diarias, operaciones de semanas)
crypto_f = Fibonacci (velas de 4 h)
us_f / byma_f = Fibonacci en acciones (velas diarias), con capital propio para compararlo con la estrategia técnica
"crypto" es el mercado anterior; se mantiene solo para leer la bitácora vieja."""
import re

MKT = {"crypto_d": "Cripto diario", "crypto_t": "Cripto tendencia", "crypto_f": "Cripto Fibonacci", "crypto": "Cripto (anterior)",
       "us": "EE.UU.", "byma": "BYMA", "us_f": "EE.UU. Fibonacci", "byma_f": "BYMA Fibonacci"}
CUR = {"crypto_d": "USDT", "crypto_t": "USDT", "crypto_f": "USDT", "crypto": "USDT", "us": "USD", "byma": "ARS", "us_f": "USD", "byma_f": "ARS"}
ACTIVE = ("crypto_d", "crypto_t", "crypto_f", "us", "byma", "us_f", "byma_f")
CRYPTO_STRATS = ("crypto_d", "crypto_t", "crypto_f")
FIB_STOCKS = ("us_f", "byma_f")
FIB_MARKETS = ("crypto_f", *FIB_STOCKS)
SUFFIX = {"crypto_d": " [D]", "crypto_t": " [T]", "crypto_f": " [F]", "us_f": " [F]", "byma_f": " [F]"}


def is_crypto(market):
    return str(market).startswith("crypto")


def base_market(market):
    if is_crypto(market):
        return "crypto"
    return {"us_f": "us", "byma_f": "byma"}.get(market, market)


def label_for(symbol, market):
    if base_market(market) == "byma" and not symbol.endswith(".BA"):
        symbol += ".BA"
    return symbol + SUFFIX.get(market, "")


def base_symbol(label):
    s = re.sub(r" \[[DTF]\]$", "", label)
    return s[:-3] if s.endswith(".BA") else s
