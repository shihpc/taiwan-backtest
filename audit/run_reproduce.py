#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稽核重現: 主張 A/B/C 原版數字 parity + 修正引擎(含起始權益 MDD / gap 成交模型)對照
輸出: audit/out/abc_results.csv, audit/out/daily_diff_a16_a19.csv
執行: python3 audit/run_reproduce.py  (repo 根目錄, 免 token 免網路)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from engine import max_drawdown, signal_bucket, simulate_day  # noqa: E402

COST_MOD, COST_HIST = 2.0, 0.0
SL = 0.0075


def old_mdd(pnls):  # 原公式(無起始權益), 供對照
    eq = pd.Series(pnls).cumsum()
    return float((eq - eq.cummax()).min()) if len(pnls) else 0.0


def sox_map(path):
    s = pd.read_parquet(path).sort_values("date")
    s["ret"] = s.Close.pct_change()
    s = s.dropna()
    return s.date.to_numpy(), s.ret.to_numpy()


def modern_days():
    """analysis19 口徑: day=08:45-13:44, len>=200"""
    bars = pd.read_parquet("data/all_bars.parquet")
    bars = bars[bars["date"] >= "2023-01-01"]
    sd, sr = sox_map("data/us_sox.parquet")
    for date, g in bars.groupby("date"):
        ix = np.searchsorted(sd, date) - 1
        if ix < 0:
            continue
        s = sr[ix]
        bucket, d, entry_at = signal_bucket(s)
        g = g.sort_index()
        day = g.between_time("08:45", "13:44")
        if len(day) < 200:
            yield date, s, bucket, None, "excluded:len<200", None
            continue
        if d is None:
            yield date, s, bucket, None, "flat", None
            continue
        if entry_at == "open":
            e, ei = float(day.iloc[0]["open"]), 0
        else:
            seg = day.between_time("10:00", "13:44")
            if not len(seg):
                yield date, s, bucket, None, "excluded:no_1000_bar", None
                continue
            e, ei = float(seg.iloc[0]["open"]), day.index.get_loc(seg.index[0])
        arrs = (day["open"].to_numpy(), day["high"].to_numpy(),
                day["low"].to_numpy(), float(day.iloc[-1]["close"]))
        yield date, s, bucket, (arrs, ei, e, d), "active", None


def hist_days():
    sd, sr = sox_map("data/us_sox_long.parquet")
    allb = pd.read_parquet("data/all_taiex_bars.parquet")
    for date, df in allb.groupby("date"):
        ix = np.searchsorted(sd, date) - 1
        if ix < 0:
            continue
        s = sr[ix]
        bucket, d, entry_at = signal_bucket(s)
        df = df.sort_values("minute")
        if len(df) < 200:
            yield date, s, bucket, None, "excluded:len<200", None
            continue
        if d is None:
            yield date, s, bucket, None, "flat", None
            continue
        if entry_at == "open":
            e, ei = float(df.iloc[0]["open"]), 0
        else:
            seg = df[df.minute >= "10:00:00"]
            if not len(seg):
                yield date, s, bucket, None, "excluded:no_1000_bar", None
                continue
            e, ei = float(seg.iloc[0]["open"]), int(np.searchsorted(
                df.minute.to_numpy(), "10:00:00"))
        arrs = (df["open"].to_numpy(), df["high"].to_numpy(),
                df["low"].to_numpy(), float(df.iloc[-1]["close"]))
        yield date, s, bucket, (arrs, ei, e, d), "active", None


def run_era(day_iter, cost, era, slip):
    rows = []
    for date, s, bucket, payload, status, _ in day_iter:
        if status != "active":
            rows.append(dict(date=date, yr=date[:4], bucket=bucket,
                             status=status))
            continue
        (op, hi, lo, cl), ei, e, d = payload
        r = dict(date=date, yr=date[:4], bucket=bucket, status="active",
                 entry=e, dir=d)
        for tag, model, sl_pct, sp in [("nosl_ideal", "ideal", 9.99, 0),
                                       ("sl_ideal", "ideal", SL, 0),
                                       ("sl_gap0", "gap", SL, 0),
                                       ("sl_gap_slip", "gap", SL, slip)]:
            pnl, how, ex = simulate_day(op, hi, lo, cl, ei, e, d, sl_pct,
                                        cost=cost, slip=sp, fill_model=model)
            r[f"pnl_{tag}"], r[f"how_{tag}"] = pnl, how
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(f"audit/out/trades_{era}.csv", index=False)
    return df


def summarize(df, era):
    out = []
    act = df[df.status == "active"].sort_values("date")
    for tag in ["nosl_ideal", "sl_ideal", "sl_gap0", "sl_gap_slip"]:
        p = act[f"pnl_{tag}"]
        ys = p.groupby(act.yr).sum()
        out.append(dict(era=era, model=tag, n=len(p), total=round(p.sum(), 0),
                        avg=round(p.mean(), 2),
                        pos_years=int((ys > 0).sum()), n_years=len(ys),
                        worst_year=round(ys.min(), 0),
                        mdd_old=round(old_mdd(p.tolist()), 0),
                        mdd_fixed=round(max_drawdown(p.tolist()), 0),
                        max_loss=round(p.min(), 1),
                        n_stop_gap=int((act[f"how_{tag}"] == "stop_gap").sum())))
    return pd.DataFrame(out)


if __name__ == "__main__":
    SLIP = 1.0  # gap_slip 情境的每邊不利滑價(點); 成本壓力另於研究段掃描
    res = []
    mod = run_era(modern_days(), COST_MOD, "modern", SLIP)
    res.append(summarize(mod, "modern"))
    hist = run_era(hist_days(), COST_HIST, "hist", SLIP)
    res.append(summarize(hist, "hist"))
    allr = pd.concat(res)
    allr.to_csv("audit/out/abc_results.csv", index=False)
    print(allr.to_string(index=False))

    # parity: 引擎 ideal vs 既有 v18 產物 (TP0/SL0.0075)
    print("\n== parity 對賬 (engine sl_ideal vs output/v18_bracket_*.csv) ==")
    for era, cf in [("modern", "output/v18_bracket_modern.csv"),
                    ("hist", "output/v18_bracket_hist.csv")]:
        old = pd.read_csv(cf)
        old = old[(old.tp == 0) & (old.sl == SL)][["date", "pnl"]]
        new = pd.read_csv(f"audit/out/trades_{era}.csv")
        new = new[new.status == "active"][["date", "pnl_sl_ideal"]]
        j = old.merge(new, on="date", how="outer", indicator=True)
        mism = j[(j._merge != "both") |
                 ((j.pnl - j.pnl_sl_ideal).abs() > 0.01)]
        print(f"  {era}: 舊 {len(old)} 筆 / 新 {len(new)} 筆 / 不一致 {len(mism)} 筆")
        if len(mism):
            mism.to_csv(f"audit/out/parity_mismatch_{era}.csv", index=False)

    # a16 vs a19 現代段逐日差異 (無 SL)
    print("\n== analysis16 vs analysis19 現代段逐日差異 ==")
    a16 = pd.read_csv("output/v15_v3b_modern.csv")[["date", "pnl"]]
    a16.columns = ["date", "pnl_a16"]
    a19 = pd.read_csv("audit/out/trades_modern.csv")
    a19 = a19[a19.status == "active"][["date", "pnl_nosl_ideal", "bucket"]]
    a19.columns = ["date", "pnl_a19", "bucket"]
    j = a16.merge(a19, on="date", how="outer", indicator=True)
    j["diff"] = (j.pnl_a16 - j.pnl_a19).round(2)
    only16 = j[j._merge == "left_only"]
    only19 = j[j._merge == "right_only"]
    both_diff = j[(j._merge == "both") & (j["diff"].abs() > 0.01)]
    j.to_csv("audit/out/daily_diff_a16_a19.csv", index=False)
    print(f"  僅a16 {len(only16)} 天 / 僅a19 {len(only19)} 天 / "
          f"兩邊皆有但pnl不同 {len(both_diff)} 天")
    print(f"  總差 = {j.pnl_a16.sum() - j.pnl_a19.sum():+.0f} 點 "
          f"(文件揭露值 17,438-17,492 = -54)")
    if len(only16):
        print("  僅a16 日期:", only16.date.tolist()[:8])
    if len(only19):
        print("  僅a19 日期:", only19.date.tolist()[:8])
    if len(both_diff):
        print("  pnl不同 日期:", both_diff.date.tolist()[:8])
