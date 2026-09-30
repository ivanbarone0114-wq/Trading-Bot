"""Bitácora CSV: alertas, decisiones y operaciones. Fuente para el límite de pérdida diaria."""
import csv, os
from datetime import datetime, timezone

FIELDS = ["time", "kind", "mode", "symbol", "market", "side", "qty", "price", "stop", "target", "pnl", "note"]


class Journal:
    def __init__(self, state_dir):
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "journal.csv")
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="") as f:
                csv.DictWriter(f, FIELDS).writeheader()

    def log(self, **kw):
        row = {k: kw.get(k, "") for k in FIELDS}
        row["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(self.path, "a", newline="") as f:
            csv.DictWriter(f, FIELDS).writerow(row)

    def realized_today(self, market=None):
        today = datetime.now(timezone.utc).date().isoformat()
        total = 0.0
        with open(self.path) as f:
            for r in csv.DictReader(f):
                if r["kind"] == "trade" and r["time"].startswith(today) and r["pnl"]:
                    if market is None or r["market"] == market:
                        total += float(r["pnl"])
        return total

    def rows_since(self, days):
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with open(self.path) as f:
            return [r for r in csv.DictReader(f) if r["time"] >= since]
