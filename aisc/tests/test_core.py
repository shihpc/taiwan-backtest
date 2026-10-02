# -*- coding: utf-8 -*-
"""aisc 離線測試（免 token 免網路）。執行：python3 -m pytest aisc/tests -q  或  python3 aisc/tests/test_core.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aisc import backtest_v2 as B  # noqa: E402
from aisc import config as C  # noqa: E402
from aisc import data as D  # noqa: E402
from aisc import indicators as I  # noqa: E402
from aisc import daily_table as T  # noqa: E402
from aisc import notify  # noqa: E402


def _df(closes, start="2021-01-04"):
    n = len(closes)
    d = pd.bdate_range(start, periods=n).strftime("%Y-%m-%d")
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": d, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": 1_000_000, "amount": c * 1_000_000})


def test_universe_frozen_117():
    u = C.load_universe()
    assert len(u["TW"]) == 93 and len(u["US"]) == 24
    assert {"6669", "2368", "2345", "2330"} <= {x["code"] for x in u["TW"]}
    assert u["benchmarks"]["US"]["data_id"] == "^SOX"


def test_features_no_lookahead():
    df = _df(100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 200)))
    full = I.add_features(df)
    cut = I.add_features(df.iloc[:150])
    cols = ["ma20", "ma60", "atr14", "ext", "r5", "r20", "slope60", "liq20"]
    pd.testing.assert_frame_equal(full[cols].iloc[:150].reset_index(drop=True), cut[cols].reset_index(drop=True))


def test_ext_definition():
    df = _df([100] * 70)
    f = I.add_features(df)
    assert np.isclose(f["ma20"].iloc[-1], 100) and np.isclose(f["ma60"].iloc[-1], 100)
    assert np.isclose(f["atr14"].iloc[-1], 2.0)         # high−low = 101−99
    assert np.isclose(f["ext"].iloc[-1], 0.0) and not bool(f["above60"].iloc[-1])  # C == MA60 不算之上


def test_rank_candidates_filters_and_tiebreak():
    snap = pd.DataFrame({
        "code": ["B", "A", "C", "D"], "ext": [2.0, 2.0, 5.0, 9.0], "r20": [0.1] * 4,
        "above60": [True, True, True, False], "liq20": [5e8, 5e8, 1e8, 9e8]})
    r = I.rank_candidates(snap, "TW", "ext")
    assert list(r["code"]) == ["A", "B"]          # C 流動性不足、D 在 MA60 下；同分依 code
    assert list(r["rank"]) == [1, 2]


def test_r2_filter_uses_ma60():
    bench = _df(list(np.linspace(100, 200, 80)) + list(np.linspace(200, 90, 40)))
    off = I.r2_filter(bench)
    assert not bool(off.iloc[79]) and bool(off.iloc[-1])


def test_net_return_costs():
    tw = B.net_return(100, 100, 1000, "TW")
    assert np.isclose(tw, (1 - C.TW_FEE_RATE - C.TW_TAX_RATE) / (1 + C.TW_FEE_RATE) - 1)
    us = B.net_return(100, 100, 100, "US")         # fee max(1, 0.5)=1 兩邊
    assert np.isclose(us, (10000 - 1) / (10000 + 1) - 1)
    assert B.net_return(100, 110, 0, "US") is None


def test_forward_trades_fixed_and_stop():
    c = [100.0] * 70 + [110.0] * 10
    df = _df(c)
    fw = B.forward_trades(df, "US", hold=60, notional=10000)
    # 訊號 i=0 → 進 i=1 開盤 100、出 i=61 收盤 100
    assert np.isclose(fw["net_ret"].iloc[0], B.net_return(100, 100, 100, "US"))
    assert fw["entry_date"].iloc[0] == df["date"].iloc[1] and fw["exit_date"].iloc[0] == df["date"].iloc[61]
    # 訊號 i=9 → 進 i=10、出 i=70 收盤 110
    assert np.isclose(fw["net_ret"].iloc[9], B.net_return(100, 110, 100, "US"))
    assert fw["net_ret"].iloc[-1] != fw["net_ret"].iloc[-1]  # 尾端無法完成＝NaN
    # 停損：進場 100，第 3 根收 80 → 第 4 根開盤出
    c2 = [100, 100, 100, 100, 80, 85, 90] + [100] * 70
    fs = B.forward_trades(_df(c2), "US", hold=60, notional=10000, stop_pct=0.15)
    assert np.isclose(fs["net_ret"].iloc[0], B.net_return(100, 85, 100, "US")) and fs["bars_held"].iloc[0] == 4


def test_verdict_rules():
    t = pd.DataFrame([
        {"group": "全體", "year": "all", "n": 1000, "pass": True},
        {"group": "TW", "year": "all", "n": 500, "pass": True},
        {"group": "US", "year": "all", "n": 500, "pass": True},
        {"group": "全體", "year": 2021, "n": 100, "pass": True},
        {"group": "全體", "year": 2022, "n": 100, "pass": False},
        {"group": "全體", "year": 2023, "n": 100, "pass": True},
        {"group": "全體", "year": 2024, "n": 10, "pass": False},   # 樣本 <50 不計
    ])
    assert B.verdict(t)["pass"] is True
    t.loc[1, "pass"] = False
    assert B.verdict(t)["pass"] is False


def test_s3_pass_logic():
    assert B._s3_pass(0.10, 0.10, -0.08, -0.12) is True
    assert B._s3_pass(0.08, 0.10, -0.08, -0.12) is False       # CAGR < 90%
    assert B._s3_pass(0.10, 0.10, -0.13, -0.12) is False       # 回撤沒更低
    assert B._s3_pass(float("nan"), 0.1, -0.1, -0.2) is False


def test_normalize_us_adjusts_ohlc():
    raw = pd.DataFrame({"date": ["2026-01-02"], "Adj_Close": [50.0], "Close": [100.0], "Open": [98.0],
                        "High": [102.0], "Low": [97.0], "Volume": [1000]})
    n = D.normalize(raw, "US")
    assert np.isclose(n["open"].iloc[0], 49.0) and np.isclose(n["close"].iloc[0], 50.0)
    assert np.isclose(n["amount"].iloc[0], 100.0 * 1000)
    assert D.normalize(pd.DataFrame(), "TW").empty


def test_mask_secret():
    D._TOKEN = "abcdefghijklmnop"
    s = D.mask_secret("GET ...?x=1&token=abcdefghijklmnop&y=2 abcdefghijklmnop")
    assert "abcdefghijklmnop" not in s and "token=***" in s


def test_daily_snapshot_and_render(tmp_path=None):
    uni = C.load_universe()
    small = {"TW": uni["TW"][:5], "US": uni["US"][:3], "benchmarks": uni["benchmarks"]}
    prices, benches = B.synthetic_prices(small, n_days=120, seed=3)
    snaps = [T.snapshot_market(m, small, prices, benches[m]) for m in ("TW", "US")]
    snap, meta = snaps[0]
    assert len(snap) == 5 and {"ext", "r5", "above60", "r3_pass", "r1_rank"} <= set(snap.columns)
    assert meta["r2_off"] in (True, False)
    md = T.render_md(snaps, "2026-10-02"); line = T.render_line(snaps, "2026-10-02")
    assert "待回測" in md and "不下單" in line and len(line) < 4900


def test_line_push_skips_without_env(monkeypatch=None):
    import os
    os.environ.pop("LINE_TOKEN", None); os.environ.pop("LINE_USER_ID", None)
    assert notify.push_text("x") is False


def test_end_to_end_synthetic(tmp_path=None):
    import tempfile
    uni = C.load_universe()
    small = {"TW": uni["TW"][:12], "US": uni["US"][:12], "benchmarks": uni["benchmarks"]}
    prices, benches = B.synthetic_prices(small, n_days=260, seed=11)
    out = Path(tempfile.mkdtemp()) / "run"
    res = B.run(prices, benches, small, out)
    for k in ("S1", "S2", "S3", "S4", "S5"):
        assert k in res
    assert (out / "summary.md").exists() and (out / "signal_daily.csv").exists()
    sig = pd.read_csv(out / "signal_daily.csv")
    assert (sig["n_r1"] <= C.TOP_N).all()


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1; print("FAIL", name, type(e).__name__, e)
    sys.exit(1 if fails else 0)
