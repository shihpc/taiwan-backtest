#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三階段研究跑器 — 參數與判準見 audit/research_spec.md(先 commit 後執行, 不回改)。
執行: python3 audit/run_research.py  (repo 根, 免 token)"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from engine import max_drawdown, simulate_day  # noqa: E402

SEED, B, BLOCK = 42, 2000, 10
BASE_SL = 0.0075


def signal(s, t1=0.01, t2=0.02):
    if s < -t2 or (-t1 <= s < 0):
        return None, None, ("大跌" if s < -t2 else "小跌")
    if -t2 <= s < -t1:
        return -1, "open", "跌"
    if 0 <= s < t1:
        return 1, "open", "小漲"
    if t1 <= s < t2:
        return 1, "open", "漲"
    return -1, "1000", "大漲"


def load_days(era):
    """回傳 list of dict: date,s,arrs,ei_open,ei_1000,e_open,e_1000,close + vol20"""
    if era == "modern":
        bars = pd.read_parquet("data/all_bars.parquet")
        bars = bars[bars["date"] >= "2023-01-01"]
        sx = pd.read_parquet("data/us_sox.parquet")
    else:
        bars = pd.read_parquet("data/all_taiex_bars.parquet")
        sx = pd.read_parquet("data/us_sox_long.parquet")
    sx = sx.sort_values("date")
    sx["ret"] = sx.Close.pct_change()
    sx = sx.dropna()
    sd, sr = sx.date.to_numpy(), sx.ret.to_numpy()
    days, ranges = [], []
    prev_close = None
    for date, g in bars.groupby("date"):
        if era == "modern":
            g = g.sort_index()
            day = g.between_time("08:45", "13:44")
            get_1000 = lambda: day.between_time("10:00", "13:44")
            minute_key = None
        else:
            day = g.sort_values("minute")
            get_1000 = lambda: day[day.minute >= "10:00:00"]
        ix = np.searchsorted(sd, date) - 1
        rng_pct = (float(day.high.max()) - float(day.low.min())) / prev_close \
            if (prev_close and len(day)) else np.nan
        vol20 = np.mean([r for r in ranges[-20:]]) if len(ranges) >= 20 else np.nan
        d = dict(date=date, s=(sr[ix] if ix >= 0 else np.nan), vol20=vol20,
                 status="ok")
        if len(day) < 200:
            d["status"] = "excluded:len<200"
        elif ix < 0:
            d["status"] = "excluded:no_sox"
        else:
            seg = get_1000()
            if not len(seg):
                d["status"] = "excluded:no_1000"
            else:
                ei1000 = (day.index.get_loc(seg.index[0]) if era == "modern"
                          else int(np.searchsorted(day.minute.to_numpy(),
                                                   "10:00:00")))
                d.update(op=day["open"].to_numpy(), hi=day["high"].to_numpy(),
                         lo=day["low"].to_numpy(),
                         cl=float(day.iloc[-1]["close"]),
                         e_open=float(day.iloc[0]["open"]),
                         e_1000=float(seg.iloc[0]["open"]), ei_1000=ei1000)
        days.append(d)
        if len(day):
            prev_close = float(day.iloc[-1]["close"])
            if not np.isnan(rng_pct):
                ranges.append(rng_pct)
    return days


def run_variant(days, cost, t1=0.01, t2=0.02, sl=BASE_SL, vol_k=None,
                delay=False, slip=0.0):
    """回傳 (date->pnl over 可評估日, per-trade rows)。空手=0。"""
    pnl_map, rows = {}, []
    for d in days:
        if d["status"] != "ok" or np.isnan(d["s"]):
            continue
        dirn, at, bucket = signal(d["s"], t1, t2)
        if dirn is None:
            pnl_map[d["date"]] = 0.0
            continue
        ei = 0 if at == "open" else d["ei_1000"]
        e = d["e_open"] if at == "open" else d["e_1000"]
        if delay:
            ei += 1
            if ei >= len(d["op"]):
                pnl_map[d["date"]] = 0.0
                continue
            e = float(d["op"][ei])
        sl_pct = sl
        if vol_k is not None:
            sl_pct = (float(np.clip(vol_k * d["vol20"], 0.004, 0.015))
                      if not np.isnan(d["vol20"]) else BASE_SL)
        pnl, how, _ = simulate_day(d["op"], d["hi"], d["lo"], d["cl"], ei, e,
                                   dirn, sl_pct, cost=cost, slip=slip,
                                   fill_model="gap")
        pnl_map[d["date"]] = pnl
        rows.append(dict(date=d["date"], bucket=bucket, dir=dirn, pnl=pnl,
                         how=how))
    return pnl_map, pd.DataFrame(rows)


def block_boot_ci(x, block=BLOCK, nboot=B, seed=SEED):
    x = np.asarray(x, float)
    n = len(x)
    if n < block * 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    means = np.empty(nboot)
    for i in range(nboot):
        starts = rng.integers(0, n, nb)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel() % n
        means[i] = x[idx[:n]].mean()
    return tuple(np.percentile(means, [2.5, 97.5]))


def nw_se(x, lag=10):
    x = np.asarray(x, float) - np.mean(x)
    n = len(x)
    g0 = np.mean(x * x)
    v = g0
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        v += 2 * w * np.mean(x[l:] * x[:-l])
    return np.sqrt(max(v, 0) / n)


def stats_row(name, era, pm, base_pm=None):
    dates = sorted(pm)
    x = np.array([pm[d] for d in dates])
    tot, mdd = x.sum(), max_drawdown(x)
    ci = block_boot_ci(x)
    row = dict(variant=name, era=era, n_days=len(x),
               n_active=int((x != 0).sum()), total=round(tot, 0),
               mean_daily=round(x.mean(), 2),
               ci_lo=round(ci[0], 2), ci_hi=round(ci[1], 2),
               nw_se=round(nw_se(x), 2), mdd=round(mdd, 0))
    if base_pm is not None:
        common = sorted(set(pm) & set(base_pm))
        dd = np.array([pm[d] - base_pm[d] for d in common])
        dci = block_boot_ci(dd)
        yr = pd.Series(dd, index=pd.Index([c[:4] for c in common]))
        ys = yr.groupby(level=0).sum()
        best = ys.idxmax() if len(ys) else None
        ex_best = dd[[c[:4] != best for c in common]] if best else dd
        row.update(pair_n=len(common), pair_diff=round(dd.sum(), 0),
                   pair_ci_lo=round(dci[0], 2), pair_ci_hi=round(dci[1], 2),
                   diff_ex_bestyr=round(ex_best.sum(), 0))
    return row


def main():
    all_stats, r1_rows = [], []
    for era, cost in [("modern", 2.0), ("hist", 0.0)]:
        days = load_days(era)
        base_pm, base_tr = run_variant(days, cost)
        all_stats.append(stats_row("base_v3SL_gap", era, base_pm))
        # R1 逐桶 + 移除
        for b, gg in base_tr.groupby("bucket"):
            r1_rows.append(dict(era=era, bucket=b, n=len(gg),
                                total=round(gg.pnl.sum(), 0),
                                avg=round(gg.pnl.mean(), 2),
                                stop_rate=round((gg.how != "close").mean(), 3),
                                worst=round(gg.pnl.min(), 0)))
        for b in base_tr.bucket.unique():
            drop_dates = set(base_tr[base_tr.bucket == b].date)
            pm = {d: (0.0 if d in drop_dates else v)
                  for d, v in base_pm.items()}
            all_stats.append(stats_row(f"R1_drop_{b}", era, pm, base_pm))
        # R2 波動度停損
        for k in [0.5, 1.0]:
            pm, _ = run_variant(days, cost, vol_k=k)
            all_stats.append(stats_row(f"R2_volstop_k{k}", era, pm, base_pm))
        # R3 門檻擾動(單變量)
        for tag, kw in [("t1_0.75", dict(t1=0.0075)), ("t1_1.25", dict(t1=0.0125)),
                        ("t2_1.75", dict(t2=0.0175)), ("t2_2.25", dict(t2=0.0225)),
                        ("sl_0.65", dict(sl=0.0065)), ("sl_0.85", dict(sl=0.0085))]:
            pm, _ = run_variant(days, cost, **kw)
            all_stats.append(stats_row(f"R3_{tag}", era, pm, base_pm))
        # R4 成本壓力
        for c in [2, 4, 6, 8]:
            pm, tr = run_variant(days, c)
            gross = tr.pnl + c
            all_stats.append(dict(variant=f"R4_cost{c}", era=era,
                                  n_active=len(tr),
                                  total=round(tr.pnl.sum(), 0),
                                  mean_daily=round(np.mean(list(pm.values())), 2),
                                  breakeven_cost=round(gross.mean(), 1),
                                  mdd=round(max_drawdown(
                                      [pm[d] for d in sorted(pm)]), 0)))
        # R5 一根延遲
        pm, _ = run_variant(days, cost, delay=True)
        all_stats.append(stats_row("R5_delay1bar", era, pm, base_pm))
        # bootstrap 敏感度
        x = np.array([base_pm[d] for d in sorted(base_pm)])
        for blk in [5, 20]:
            ci = block_boot_ci(x, block=blk)
            all_stats.append(dict(variant=f"base_ci_block{blk}", era=era,
                                  ci_lo=round(ci[0], 2), ci_hi=round(ci[1], 2)))
    res = pd.DataFrame(all_stats)
    res.to_csv("audit/out/research_results.csv", index=False)
    pd.DataFrame(r1_rows).to_csv("audit/out/research_R1_buckets.csv", index=False)
    print(pd.DataFrame(r1_rows).to_string(index=False))
    print()
    cols = ["variant", "era", "n_active", "total", "mean_daily", "ci_lo",
            "ci_hi", "mdd", "pair_diff", "pair_ci_lo", "pair_ci_hi",
            "diff_ex_bestyr", "breakeven_cost"]
    print(res.reindex(columns=cols).to_string(index=False))
    # R6 口數情境(公式表, 用 base 現代交易)
    _, tr = run_variant(load_days("modern"), 2.0)
    risk_per_lot = tr.pnl.map(lambda _: 0) # placeholder col
    ent = pd.read_csv("audit/out/trades_modern.csv")
    ent = ent[ent.status == "active"]
    rl = (ent.entry * BASE_SL * 50)
    print("\nR6 口數情境(資金90萬, 保證金175,250/口):")
    for bud_pct in [0.01, 0.02]:
        budget = 900000 * bud_pct
        lots = np.minimum(np.floor(budget / rl),
                          np.floor(900000 / 175250)).clip(0)
        print(f"  風險預算 {bud_pct:.0%}: 平均口數 {lots.mean():.2f}, "
              f"0 口日比例 {(lots == 0).mean():.0%}, 最大 {lots.max():.0f} 口")


if __name__ == "__main__":
    main()
