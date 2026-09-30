class Broker:
    name = "base"

    def cash(self, market): raise NotImplementedError
    def position(self, symbol): raise NotImplementedError      # -> dict {qty, avg, stop, target} o None
    def open_count(self, market=None): raise NotImplementedError
    def buy(self, symbol, market, qty, price, stop=None, target=None): raise NotImplementedError
    def sell(self, symbol, market, qty, price): raise NotImplementedError  # -> pnl realizado
