#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v17: % 停利出場 x 2005-2022 十八年 (TAIEX 完整分K, 未扣成本, 純方向驗證)
  playbook v3 規則, 出場改「獲利達 x% 平倉, 否則 13:30 收盤平」
"""
import numpy as np
import pandas as pd
from pathlib import Path

PCTS = [None, 0.005, 0.0075, 0.01, 0.015]

sox = pd.read_parquet("data/us_sox_long.parquet").sort_values("date")
sox["ret"] = sox.Close.pct_change(); sox = sox.dropna()
sd = sox.date.to_numpy(); sr = sox.ret.to_numpy()

rows = []
for p in sorted(Path("data/taiex_bars").glob("*.parquet")):
    date = p.stem
    ix = np.searchsorted(sd, date) - 1
    if ix < 0:
        continue
    s = sr[ix]
    if s < -0.02 or (-0.01 <= s < 0):
        continue
    if -0.02 <= s < -0.01:
        d, entry_at = -1, "0900"
    elif 0 <= s < 0.02:
        d, entry_at = 1, "0900"
    else:
        d, entry_at = -1, "1000"
    df = pd.read_parquet(p).sort_values("minute")
    if len(df) < 200:
        continue
    if entry_at == "0900":
        e = float(df.iloc[0]["open"]); ei = 0
    else:
        seg = df[df.minute >= "10:00:00"]
        if not len(seg):
            continue
        e = float(seg.iloc[0]["open"]); ei = df.index.get_loc(seg.index[0])
    hi = df["high"].to_numpy(); lo = df["low"].to_numpy()
    c = float(df.iloc[-1]["close"])
    fav = (hi - e) if d == 1 else (e - lo)
    fav = fav.copy(); fav[:ei] = -1e9
    for pct in PCTS:
        if pct is None:
            pnl = (c - e) * d
        else:
            ok = np.nonzero(fav >= e * pct)[0]
            pnl = e * pct if len(ok) else (c - e) * d
        rows.append(dict(date=date, yr=date[:4], pct=pct or 0, pnl=pnl))

tr = pd.DataFrame(rows)
print("歷史段 2005-2022 (TAIEX, 未扣成本):")
print(f"{'出場':<14s}{'總計':>10s}{'avg':>7s}{'正年數':>7s}{'最差年':>16s}{'MDD':>8s}")
for pct, gg in tr.groupby("pct"):
    label = "抱到收盤" if pct == 0 else f"獲利{pct*100:.2f}%出場"
    ys = gg.groupby("yr").pnl.sum()
    eq = gg.sort_values("date").pnl.cumsum()
    mdd = (eq - eq.cummax()).min()
    print(f"{label:<14s}{gg.pnl.sum():>+10.0f}{gg.pnl.mean():>+7.1f}"
          f"{int((ys>0).sum()):>4d}/{len(ys):<2d}"
          f"{ys.min():>+9.0f}({ys.idxmin()}){mdd:>8.0f}")
tr.to_csv("output/v17_pct_exit_hist.csv", index=False)
