"""Acciones/ETFs de EE.UU. vía Alpaca REST (paper o real)."""
import os, requests


class AlpacaBroker:
    name = "alpaca"

    def __init__(self, paper=True):
        self.base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.h = {"APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY", ""),
                  "APCA-API-SECRET-KEY": os.getenv("ALPACA_API_SECRET", "")}

    def _req(self, method, path, **kw):
        r = requests.request(method, self.base + path, headers=self.h, timeout=15, **kw)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def cash(self, market): return float(self._req("GET", "/v2/account")["cash"])

    def position(self, symbol):
        p = self._req("GET", f"/v2/positions/{symbol}")
        return {"qty": float(p["qty"]), "avg": float(p["avg_entry_price"])} if p else None

    def open_count(self, market=None): return len(self._req("GET", "/v2/positions") or [])

    def _order(self, symbol, qty, side):
        return self._req("POST", "/v2/orders", json={"symbol": symbol, "qty": str(round(qty, 6)),
                                                     "side": side, "type": "market", "time_in_force": "day"})

    def buy(self, symbol, market, qty, price, stop=None, target=None):
        self._order(symbol, qty, "buy"); return price

    def sell(self, symbol, market, qty, price):
        self._order(symbol, qty, "sell"); return None, price
