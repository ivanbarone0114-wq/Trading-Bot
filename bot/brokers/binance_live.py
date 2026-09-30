"""Ejecución real/testnet en Binance spot vía ccxt. Los stops se gestionan por software en cada ciclo."""
import os


class BinanceBroker:
    name = "binance"

    def __init__(self, testnet=True):
        import ccxt
        self.ex = ccxt.binance({"apiKey": os.getenv("BINANCE_API_KEY"),
                                "secret": os.getenv("BINANCE_API_SECRET"),
                                "enableRateLimit": True})
        if testnet:
            self.ex.set_sandbox_mode(True)
        self.ex.load_markets()

    def cash(self, market):
        return float(self.ex.fetch_balance()["free"].get("USDT", 0.0))

    def position(self, symbol):
        base = symbol.split("/")[0]
        qty = float(self.ex.fetch_balance()["free"].get(base, 0.0))
        min_amt = (self.ex.market(symbol)["limits"]["amount"]["min"] or 0)
        return {"qty": qty, "avg": None} if qty > min_amt else None

    def open_count(self, market=None):
        return 0  # se controla por bitácora; simplificado

    def buy(self, symbol, market, qty, price, stop=None, target=None):
        qty = float(self.ex.amount_to_precision(symbol, qty))
        o = self.ex.create_order(symbol, "market", "buy", qty)
        return o.get("average") or price

    def sell(self, symbol, market, qty, price):
        qty = float(self.ex.amount_to_precision(symbol, qty))
        o = self.ex.create_order(symbol, "market", "sell", qty)
        return None, o.get("average") or price
