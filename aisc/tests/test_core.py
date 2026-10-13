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
from aisc import universe_refresh as U  # noqa: E402


def _df(closes, start="2021-01-04"):
    n = len(closes)
    d = pd.bdate_range(start, periods=n).strftime("%Y-%m-%d")
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": d, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": 1_000_000, "amount": c * 1_000_000})


def test_universe_frozen_117():
    u = C.load_universe(C.UNIVERSE_V1_PATH)
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


def test_clean_drops_zero_volume_and_clips_open():
    df = _df([100.0, 101.0, 102.0, 103.0])
    df.loc[1, "volume"] = 0                     # 非交易佔位列
    df.loc[2, "open"] = 180.0                   # open 超出 [low, high]
    out = D.clean(df)
    assert len(out) == 3 and "2021-01-05" not in set(out["date"])
    row = out[out["date"] == "2021-01-06"].iloc[0]
    assert row["low"] <= row["open"] <= row["high"] and np.isclose(row["open"], row["high"])
    assert np.isclose(row["close"], 102.0)      # 只動 open


def test_benchmark_not_cleaned_by_zero_volume():
    """指數基準 volume 恆為 0，load_benchmark 不得套 clean()，否則 R2 濾網整條失效。"""
    import tempfile
    uni = C.load_universe()
    raw = pd.DataFrame({"date": ["2026-01-02", "2026-01-05"], "open": [100, 101], "max": [101, 102], "min": [99, 100],
                        "close": [100.5, 101.5], "Trading_Volume": [0, 0], "Trading_money": [0, 0], "spread": [0, 1],
                        "Trading_turnover": [0, 0]})
    old = C.PRICE_CACHE_DIR
    C.PRICE_CACHE_DIR = Path(tempfile.mkdtemp())
    try:
        bench = D.load_benchmark("TW", uni, fetch=lambda *a, **k: raw)
        stock = D.load_prices("TW", "9999", fetch=lambda *a, **k: raw)
    finally:
        C.PRICE_CACHE_DIR = old
    assert len(bench) == 2 and len(stock) == 0


def test_portfolio_sizing_tracks_equity():
    """每槽名目＝當下淨值÷10：淨值翻倍後，新倉股數也應約翻倍。"""
    uni = {"TW": [], "US": [{"code": "X", "name": "X"}], "benchmarks": C.load_universe()["benchmarks"]}
    n = 200
    c = np.concatenate([np.full(70, 100.0), np.linspace(100, 300, 130)])   # 單邊上漲
    df = _df(c)
    df["amount"] = 1e9
    panel = B.build_panel({("US", "X"): df}, "US", uni)
    dates = B.market_dates(panel, start="2021-01-04")
    eq = B.simulate_portfolio(panel, "US", dates, None, use_r2=False, slots=1)
    assert eq["equity"].iloc[-1] > 1.5          # 單槽滿倉跟著漲，不會被釘在初始名目而稀釀
    # 對照：若名目釘死初始資金，淨值 2 倍時曝險只剩一半 → 最終淨值會明顯更低
    e = eq["equity"].to_numpy()
    assert e[-1] / e[len(e) // 2] > 1.2


def test_s4_no_sample_label():
    import tempfile
    uni = C.load_universe()
    small = {"TW": uni["TW"][:6], "US": uni["US"][:6], "benchmarks": uni["benchmarks"]}
    prices, benches = B.synthetic_prices(small, n_days=200, seed=5)
    res = B.run(prices, benches, small, Path(tempfile.mkdtemp()) / "r", oos_start="2099-01-01")
    assert res["S4"]["pass"] is None and res["S4"]["status"] == "無樣本"


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


def _bench(dates, closes):
    c = np.asarray(closes, float)
    return pd.DataFrame({"date": list(dates), "open": c, "high": c, "low": c, "close": c,
                         "volume": 1, "amount": 1.0})


def test_daily_bench_aligned_to_stock_date():
    """大盤比個股多一天（台股 15:30 班的常態）時，R2／MA60 必須取個股資料日那天，不取大盤最新一天。"""
    uni = C.load_universe()
    small = {"TW": uni["TW"][:3], "US": [], "benchmarks": uni["benchmarks"]}
    prices = {("TW", x["code"]): _df(np.linspace(100, 130, 80)) for x in small["TW"]}
    stock_dates = prices[("TW", small["TW"][0]["code"])]["date"].tolist()
    extra = (pd.Timestamp(stock_dates[-1]) + pd.offsets.BDay(1)).strftime("%Y-%m-%d")
    # 大盤前 80 天穩定 100，多出來的那天暴跌到 1（若誤用，R2 會變成關）
    bench = _bench(stock_dates + [extra], [100.0] * 80 + [1.0])
    snap, meta = T.snapshot_market("TW", small, prices, bench)
    # 先斷言行為（舊版在這裡就會失敗：拿到大盤最後一天、R2 關），再看新欄位
    assert meta["bench_date"] == stock_dates[-1] and meta["bench_close"] == 100.0
    assert meta["r2_off"] is False
    assert meta["data_date"] == stock_dates[-1] and meta["n_stale"] == 0
    # 指標數值不受影響
    snap2, _ = T.snapshot_market("TW", small, prices, bench.iloc[:80])
    assert snap["ext"].equals(snap2["ext"]) and snap["r1_rank"].equals(snap2["r1_rank"])


def test_daily_dates_per_market_and_stale():
    uni = C.load_universe()
    small = {"TW": uni["TW"][:3], "US": uni["US"][:2], "benchmarks": uni["benchmarks"]}
    prices = {("TW", x["code"]): _df(np.linspace(100, 130, 80)) for x in small["TW"]}
    prices[("TW", small["TW"][2]["code"])] = _df(np.linspace(100, 130, 79))   # 一檔落後一天
    prices.update({("US", x["code"]): _df(np.linspace(50, 60, 81)) for x in small["US"]})
    tw_last = prices[("TW", small["TW"][0]["code"])]["date"].iloc[-1]
    us_last = prices[("US", small["US"][0]["code"])]["date"].iloc[-1]
    benches = {m: _bench(pd.bdate_range("2021-01-04", periods=90).strftime("%Y-%m-%d"), [100.0] * 90)
               for m in ("TW", "US")}
    snaps = [T.snapshot_market(m, small, prices, benches[m]) for m in ("TW", "US")]
    tw, us = snaps[0][1], snaps[1][1]
    assert tw["data_date"] == tw_last and us["data_date"] == us_last and us_last > tw_last
    assert tw["n_stale"] == 1 and us["n_stale"] == 0
    assert tw["bench_date"] == tw_last and us["bench_date"] == us_last
    assert T.asof_date(snaps) == us_last
    md = T.render_md(snaps, T.asof_date(snaps)); line = T.render_line(snaps, T.asof_date(snaps))
    assert f"TW {tw_last}｜US {us_last}" in md and f"資料日：{tw_last}（1 檔" in md
    assert f"■ TW 資料日 {tw_last}（1 檔" in line and f"■ US 資料日 {us_last}" in line


def test_daily_empty_bench_and_no_prices():
    uni = C.load_universe()
    small = {"TW": uni["TW"][:2], "US": [], "benchmarks": uni["benchmarks"]}
    empty = _bench([], [])
    snap, meta = T.snapshot_market("TW", small, {}, empty)
    assert meta["data_date"] is None and meta["bench_date"] is None and meta["r2_off"] is None
    assert T.asof_date([(snap, meta)]) is None
    prices = {("TW", x["code"]): _df(np.linspace(100, 130, 80)) for x in small["TW"]}
    late = _bench(["2030-01-01"], [100.0])   # 大盤只有比個股晚的日子 → 截完為空
    _, meta2 = T.snapshot_market("TW", small, prices, late)
    assert meta2["bench_date"] is None and meta2["r2_off"] is None
    T.render_md([(snap, meta)], "2026-10-02"); T.render_line([(snap, meta)], "2026-10-02")


def _screen(n=93, gen="2026-10-10T22:40:00+08:00", min_feps=20, start=1000):
    rows = [{"code": str(start + i), "name": f"股{i}"} for i in range(n)]
    return {"date": "2026-10-10", "generated_at": gen, "min_feps": min_feps, "n": n, "rows": rows}


def test_universe_refresh_due_boundaries():
    import datetime as dt
    uni = {"frozen_at": "2026-10-02"}
    assert U.refresh_due(uni, dt.date(2026, 10, 10)) is False          # 10 號：月營收當天，未到期
    assert U.refresh_due(uni, dt.date(2026, 10, 11)) is True
    assert U.refresh_due(uni, dt.date(2026, 10, 14)) is True           # 11 號後第一班（逢假日／週末）
    uni2 = {"frozen_at": "2026-10-02", "tw_refreshed_at": "2026-10-12"}
    assert U.refresh_due(uni2, dt.date(2026, 10, 31)) is False         # 當月已換過
    assert U.refresh_due(uni2, dt.date(2026, 11, 10)) is False
    assert U.refresh_due(uni2, dt.date(2026, 11, 11)) is True          # 跨月
    assert U.refresh_due({"frozen_at": "2026-10-11"}, dt.date(2026, 10, 20)) is False   # 11 號當天換的算數


def test_universe_refresh_guards():
    import datetime as dt
    today = dt.date(2026, 10, 12)
    ok = U.validate_screen(_screen(), today, 93)
    assert len(ok) == 93 and ok == sorted(ok, key=lambda x: x["code"])
    bad = {
        "rows 空": _screen(n=0),
        "min_feps": _screen(min_feps=15),
        "月營收前的版本": _screen(gen="2026-10-09T22:40:00+08:00"),
        "未來": _screen(gen="2026-10-13T01:00:00+08:00"),
        "殘缺": _screen(n=40),
        "gen 壞": _screen(gen="nope"),
    }
    s = _screen(); s["n"] = 92; bad["n 不符"] = s
    s = _screen(); s["rows"][3]["code"] = "<x>"; bad["代號格式"] = s
    s = _screen(); s["rows"][3]["code"] = s["rows"][2]["code"]; bad["重複"] = s
    s = _screen(); s["rows"][3]["code"] = "2330\n"; bad["代號尾端換行"] = s
    s = _screen(); s["rows"][3]["name"] = " "; bad["空名稱"] = s
    for why, sc in bad.items():
        try:
            U.validate_screen(sc, today, 93)
        except U.ScreenRejected:
            continue
        raise AssertionError(f"守門沒擋：{why}")
    # UTC 時戳換算台北：10-09T16:30Z＝台北 10-10 00:30 → 通過
    assert U.validate_screen(_screen(gen="2026-10-09T16:30:00+00:00"), today, 93)
    # --force 在 10 號前：下限退到上個月 10 號
    assert U.validate_screen(_screen(gen="2026-09-20T22:00:00+08:00"), dt.date(2026, 10, 5), 93)


def test_universe_refresh_run_writes_and_keeps_us():
    import datetime as dt
    import json as _json
    import tempfile
    src = C.load_universe(C.UNIVERSE_V1_PATH)
    path = Path(tempfile.mkdtemp()) / "universe.json"
    path.write_text(_json.dumps(src, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    keep = src["TW"][:80]
    sc = {"date": "2026-10-12", "generated_at": "2026-10-12T22:40:00+08:00", "min_feps": 20,
          "rows": keep + [{"code": "9999", "name": "新股"}]}
    sc["n"] = len(sc["rows"])
    # 未到期：不抓、不寫
    rc, msg = U.run(path, dt.date(2026, 10, 9), fetch=lambda: (_ for _ in ()).throw(AssertionError("不該抓")))
    assert rc == 0 and "未到期" in msg
    # dry-run：不寫檔
    before = path.read_text(encoding="utf-8")
    rc, _ = U.run(path, dt.date(2026, 10, 13), fetch=lambda: sc, dry_run=True)
    assert rc == 0 and path.read_text(encoding="utf-8") == before
    # 抓取失敗與守門不過：rc=5、不寫檔
    rc, msg = U.run(path, dt.date(2026, 10, 13), fetch=lambda: (_ for _ in ()).throw(OSError("net")))
    assert rc == 5 and "::warning::" in msg and path.read_text(encoding="utf-8") == before
    rc, _ = U.run(path, dt.date(2026, 10, 13), fetch=lambda: dict(sc, min_feps=10))
    assert rc == 5 and path.read_text(encoding="utf-8") == before
    # 實際換池
    rc, msg = U.run(path, dt.date(2026, 10, 13), fetch=lambda: sc)
    u = C.load_universe(path)
    assert rc == 0 and len(u["TW"]) == 81 and u["tw_refreshed_at"] == "2026-10-13"
    assert u["US"] == src["US"] and u["benchmarks"] == src["benchmarks"] and u["frozen_at"] == src["frozen_at"]
    ch = u["changes"][-1]
    assert ch["added"] == ["9999"] and len(ch["removed"]) == 13 and ch["source"]["date"] == "2026-10-12"
    assert u["changes"][0] == src["changes"][0]
    # 同月再跑：未到期
    rc, msg = U.run(path, dt.date(2026, 10, 20), fetch=lambda: sc)
    assert rc == 0 and "未到期" in msg
    # v1 凍結檔不受影響
    assert len(C.load_universe(C.UNIVERSE_V1_PATH)["TW"]) == 93
    assert "TW 81 檔（2026-10-13 換池，依 screen 2026-10-12）" in T.pool_line(u)
    assert "TW 93 檔（2026-10-02 初始凍結）" in T.pool_line(src)


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
