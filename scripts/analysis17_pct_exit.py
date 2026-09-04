#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v16: playbook v3 的出場改「當日獲利達 x% 即平倉, 否則收盤平」 vs 原版抱到收盤
  % 以進場價計 (跨 20 年可比, 不像固定點數會被指數水位扭曲)
  現代段: 2023-2026 小台 1 分 K, 成本 2 點
"""
import numpy as np
import pandas as pd
from pathlib import Path

COST = 2.0
PCTS = [None, 0.003, 0.005, 0.0075, 0.01, 0.015]   # None=原版抱到收盤

bars = pd.read_parquet("data/all_bars.parquet")
bars = bars[bars["date"] >= "2023-01-01"]
sox = pd.read_parquet("data/us_sox.parquet").sort_values("date")
sox["ret"] = sox.Close.pct_change(); sox = sox.dropna()
sd = sox.date.to_numpy(); sr = sox.ret.to_numpy()

rows = []
for date, g in bars.groupby("date"):
    ix = np.searchsorted(sd, date) - 1
    if ix < 0:
        continue
    s = sr[ix]
    if s < -0.02 or (-0.01 <= s < 0):
        continue  # 空手桶
    if -0.02 <= s < -0.01:
        d, entry_at = -1, "0845"
    elif 0 <= s < 0.02:
        d, entry_at = 1, "0845"
    else:
        d, entry_at = -1, "1000"
    g = g.sort_index()
    day = g.between_time("08:45", "13:44")
    if len(day) < 200:
        continue
    if entry_at == "0845":
        e = float(day.iloc[0]["open"]); ei = 0
    else:
        seg = day.between_time("10:00", "13:44")
        if not len(seg):
            continue
        e = float(seg.iloc[0]["open"])
        ei = day.index.get_loc(seg.index[0])
    hi = day["high"].to_numpy(); lo = day["low"].to_numpy()
    c = float(day.iloc[-1]["close"])
    fav = (hi - e) if d == 1 else (e - lo)
    fav[:ei] = -1e9
    for pct in PCTS:
        if pct is None:
            pnl, how = (c - e) * d - COST, "close"
        else:
            tgt = e * pct
            ok = np.nonzero(fav >= tgt)[0]
            if len(ok):
                pnl, how = tgt - COST, "target"
            else:
                pnl, how = (c - e) * d - COST, "close"
        rows.append(dict(date=date, yr=date[:4], pct=pct or 0, pnl=pnl, how=how))

tr = pd.DataFrame(rows)
print("現代段 2023-2026 (小台, 扣成本2點):")
print(f"{'出場':<14s}" + "".join(f"{y:>9s}" for y in ["2023","2024","2025","2026"]) +
      f"{'總計':>9s}{'avg':>7s}{'勝率':>6s}{'觸利率':>7s}{'MDD':>7s}")
for pct, gg in tr.groupby("pct"):
    label = "抱到收盤" if pct == 0 else f"獲利{pct*100:.2f}%出場"
    ys = gg.groupby("yr").pnl.sum()
    eq = gg.sort_values("date").pnl.cumsum()
    mdd = (eq - eq.cummax()).min()
    print(f"{label:<14s}" +
          "".join(f"{ys.get(y, 0):>+9.0f}" for y in ["2023","2024","2025","2026"]) +
          f"{gg.pnl.sum():>+9.0f}{gg.pnl.mean():>+7.1f}"
          f"{(gg.pnl>0).mean():>6.0%}{(gg.how=='target').mean():>7.0%}{mdd:>7.0f}")
tr.to_csv("output/v16_pct_exit_modern.csv", index=False)
