#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v18: playbook v3 + 停損/停利括號 (皆以進場價 % 計) 雙時代掃描
  出場: 停損 SL% / 停利 TP% / 皆未觸 -> 收盤平; 同一根 K 保守先停損
  現代段 2023-2026 小台(成本2點) + 歷史段 2005-2022 TAIEX(未扣成本)
"""
import numpy as np
import pandas as pd
from pathlib import Path

TPS = [0.0075, 0.01, 0.015, None]
SLS = [0.005, 0.0075, 0.01, 0.015, None]

def sim_day(hi, lo, close_px, e, ei, d, tp, sl, cost):
    tp_px = e * tp if tp else None
    sl_px = e * sl if sl else None
    for j in range(ei, len(hi)):
        adv = (e - lo[j]) if d == 1 else (hi[j] - e)   # 不利波動
        fav = (hi[j] - e) if d == 1 else (e - lo[j])   # 有利波動
        if sl_px is not None and adv >= sl_px:
            return -sl_px - cost, "stop"
        if tp_px is not None and fav >= tp_px:
            return tp_px - cost, "target"
    return (close_px - e) * d - cost, "close"

def direction(s):
    if s < -0.02 or (-0.01 <= s < 0):
        return None, None
    if -0.02 <= s < -0.01:
        return -1, "open"
    if 0 <= s < 0.02:
        return 1, "open"
    return -1, "1000"

def run_era(day_iter, cost, era):
    rows = []
    for date, hi, lo, close_px, e, ei, d in day_iter:
        for tp in TPS:
            for sl in SLS:
                pnl, how = sim_day(hi, lo, close_px, e, ei, d, tp, sl, cost)
                rows.append(dict(date=date, yr=date[:4],
                                 tp=tp or 0, sl=sl or 0, pnl=pnl, how=how))
    tr = pd.DataFrame(rows)
    tr.to_csv(f"output/v18_bracket_{era}.csv", index=False)
    print(f"\n===== {era} =====")
    print(f"{'TP':>6s}{'SL':>6s}{'總計':>9s}{'avg':>7s}{'勝率':>6s}"
          f"{'正年':>6s}{'最差年':>8s}{'MDD':>7s}{'最大單虧':>8s}{'停損率':>7s}")
    for (tp, sl), gg in tr.groupby(["tp", "sl"]):
        ys = gg.groupby("yr").pnl.sum()
        eq = gg.sort_values("date").pnl.cumsum()
        mdd = (eq - eq.cummax()).min()
        print(f"{tp*100 if tp else 0:>5.2f}%{sl*100 if sl else 0:>5.2f}%"
              f"{gg.pnl.sum():>+9.0f}{gg.pnl.mean():>+7.1f}"
              f"{(gg.pnl>0).mean():>6.0%}{int((ys>0).sum()):>4d}/{len(ys):<2d}"
              f"{ys.min():>+8.0f}{mdd:>7.0f}{gg.pnl.min():>8.0f}"
              f"{(gg.how=='stop').mean():>7.0%}")
    return tr

def modern_days():
    bars = pd.read_parquet("data/all_bars.parquet")
    bars = bars[bars["date"] >= "2023-01-01"]
    sox = pd.read_parquet("data/us_sox.parquet").sort_values("date")
    sox["ret"] = sox.Close.pct_change(); sox = sox.dropna()
    sd = sox.date.to_numpy(); sr = sox.ret.to_numpy()
    for date, g in bars.groupby("date"):
        ix = np.searchsorted(sd, date) - 1
        if ix < 0:
            continue
        d, entry_at = direction(sr[ix])
        if d is None:
            continue
        g = g.sort_index()
        day = g.between_time("08:45", "13:44")
        if len(day) < 200:
            continue
        if entry_at == "open":
            e, ei = float(day.iloc[0]["open"]), 0
        else:
            seg = day.between_time("10:00", "13:44")
            if not len(seg):
                continue
            e, ei = float(seg.iloc[0]["open"]), day.index.get_loc(seg.index[0])
        yield (date, day["high"].to_numpy(), day["low"].to_numpy(),
               float(day.iloc[-1]["close"]), e, ei, d)

def hist_days():
    sox = pd.read_parquet("data/us_sox_long.parquet").sort_values("date")
    sox["ret"] = sox.Close.pct_change(); sox = sox.dropna()
    sd = sox.date.to_numpy(); sr = sox.ret.to_numpy()
    allb = pd.read_parquet("data/all_taiex_bars.parquet")
    for date, df in allb.groupby("date"):
        ix = np.searchsorted(sd, date) - 1
        if ix < 0:
            continue
        d, entry_at = direction(sr[ix])
        if d is None:
            continue
        df = df.sort_values("minute")
        if len(df) < 200:
            continue
        if entry_at == "open":
            e, ei = float(df.iloc[0]["open"]), 0
        else:
            seg = df[df.minute >= "10:00:00"]
            if not len(seg):
                continue
            e, ei = float(seg.iloc[0]["open"]), int(np.searchsorted(
                df.minute.to_numpy(), "10:00:00"))
        yield (date, df["high"].to_numpy(), df["low"].to_numpy(),
               float(df.iloc[-1]["close"]), e, ei, d)

run_era(modern_days(), 2.0, "modern")
run_era(hist_days(), 0.0, "hist")
