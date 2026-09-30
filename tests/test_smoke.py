"""Pruebas rápidas offline: python -m pytest tests  (o python tests/test_smoke.py)"""
import os, sys, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml
from bot.data import synthetic_ohlcv
from bot.strategy import evaluate
from bot.backtest import run
from bot.risk import RiskManager
from bot.brokers.paper import PaperBroker
from bot import main as m

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.yaml")))


def test_signal_fields():
    s = evaluate(synthetic_ohlcv(300, 1), CFG["strategy"], "X")
    assert s.action in ("BUY", "SELL", "HOLD") and -1 <= s.score <= 1
    if s.action == "BUY":
        assert s.stop < s.price < s.target


def test_risk_sizing():
    r = RiskManager(CFG["risk"], {"us": 1000})
    q = r.size("us", 100, 95)            # riesgo 1% = 10 → 2 u; tope 20% = 2 u
    assert abs(q - 2.0) < 1e-9


def test_paper_roundtrip():
    d = tempfile.mkdtemp()
    b = PaperBroker(d, {"us": 1000}, fee=0, slippage=0)
    b.buy("SPY", "us", 2, 100, 95, 110)
    pnl, _ = b.sell("SPY", "us", 2, 110)
    assert abs(pnl - 20) < 1e-9 and abs(b.cash("us") - 1020) < 1e-9
    shutil.rmtree(d)


def test_backtest_runs():
    res = run(synthetic_ohlcv(800, 3), CFG["strategy"], CFG["risk"])
    assert res["operaciones"] >= 1


def test_cycle_paper_offline():
    d = tempfile.mkdtemp()
    cfg = dict(CFG, state_dir=d)
    cfg["watchlist"] = [{"symbol": f"SYN{i}", "market": "us", "timeframe": "1d", "htf": "1wk"} for i in range(40)]
    cfg["risk"] = dict(CFG["risk"], max_open_positions=100)
    m.cycle(cfg, "paper", offline=True)
    m.cycle(cfg, "paper", offline=True)   # segundo ciclo: no duplica alertas
    assert os.path.exists(os.path.join(d, "journal.csv"))
    shutil.rmtree(d)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK", name)
