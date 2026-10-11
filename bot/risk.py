"""Gestión de riesgo: tamaño de posición por riesgo fijo, límites y kill-switch."""
import os


class RiskManager:
    def __init__(self, cfg, capital_by_market, state_dir="state"):
        self.cfg = cfg
        self.capital = capital_by_market
        self.kill_file = os.path.join(state_dir, "STOP")

    def size(self, market, entry, stop, available_cash=None):
        cap = self.capital.get(market, 0)
        dist = entry - stop
        if dist <= 0:
            return 0.0
        qty = min(cap * self.cfg["risk_per_trade"] / dist, cap * self.cfg["max_position_pct"] / entry)
        if available_cash is not None:
            qty = min(qty, available_cash / (entry * (1 + self.cfg["fee"]) * (1 + self.cfg["slippage"]) * 1.001))
        return max(qty, 0.0)

    def can_open(self, market, open_positions, realized_today, max_open=None):
        if os.path.exists(self.kill_file):
            return False, "Kill-switch activo (archivo state/STOP)"
        if open_positions >= (max_open or self.cfg["max_open_positions"]):
            return False, "Máximo de posiciones abiertas alcanzado"
        if realized_today <= -self.cfg["max_daily_loss_pct"] * self.capital.get(market, 0):
            return False, "Límite de pérdida diaria alcanzado"
        return True, "OK"
