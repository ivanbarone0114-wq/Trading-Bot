"""Paper trading: cartera simulada persistida en JSON, con comisión y slippage."""
import json, os


class PaperBroker:
    name = "paper"

    def __init__(self, state_dir, capital, fee=0.001, slippage=0.0005, fees=None):
        self.path = os.path.join(state_dir, "paper_portfolio.json")
        self.fee, self.slip = fee, slippage
        self.fees = fees or {}  # comisión distinta por mercado, ej. {"crypto": 0.001}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.s = json.load(f)
        else:
            self.s = {"cash": dict(capital), "positions": {}}
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.s, f, indent=2)

    def cash(self, market): return self.s["cash"][market]
    def position(self, symbol): return self.s["positions"].get(symbol)

    def open_count(self, market=None):
        return sum(1 for p in self.s["positions"].values() if market is None or p["market"] == market)

    def buy(self, symbol, market, qty, price, stop=None, target=None):
        fill = price * (1 + self.slip)
        fee = self.fees.get(market, self.fee)
        cost = fill * qty * (1 + fee)
        if cost > self.s["cash"][market] + 1e-9:
            raise ValueError("Saldo simulado insuficiente")
        self.s["cash"][market] -= cost
        p = self.s["positions"].get(symbol)
        if p:
            p["avg"] = (p["avg"] * p["qty"] + fill * qty) / (p["qty"] + qty)
            p["qty"] += qty
        else:
            self.s["positions"][symbol] = {"market": market, "qty": qty, "avg": fill, "stop": stop, "target": target}
        if stop is not None:
            self.s["positions"][symbol].update(stop=stop, target=target)
        self._save()
        return fill

    def sell(self, symbol, market, qty, price):
        p = self.s["positions"].get(symbol)
        if not p:
            raise ValueError("No hay posición para vender")
        qty = min(qty, p["qty"])
        fill = price * (1 - self.slip)
        fee = self.fees.get(market, self.fee)
        proceeds = fill * qty * (1 - fee)
        pnl = proceeds - p["avg"] * qty * (1 + fee)
        self.s["cash"][market] += proceeds
        p["qty"] -= qty
        if p["qty"] <= 1e-12:
            del self.s["positions"][symbol]
        self._save()
        return pnl, fill

    def summary(self, prices=None):
        prices = prices or {}
        lines = ["== Cartera simulada =="]
        for m, c in self.s["cash"].items():
            lines.append(f"Efectivo {m}: {c:,.2f}")
        for sym, p in self.s["positions"].items():
            px = prices.get(sym, p["avg"])
            lines.append(f"{sym}: {p['qty']:.6f} @ {p['avg']:,.4f} | último {px:,.4f} | "
                         f"PnL no realizado {(px - p['avg']) * p['qty']:+,.2f} | stop {p.get('stop') or '-'}")
        return "\n".join(lines)
