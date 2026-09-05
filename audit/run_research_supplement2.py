#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三階段第二批補齊(應任務書逐款要求, 2026-09-05 第三輪):
  5 開盤跳空濾網: 量化 SOX 訊號被開盤跳空吸收的程度(明定基準=同盤別前日收盤)、
    跳空濾網變體、一根延遲×滑價合併敏感度
  6 風險口數: 固定 1 口 vs 依每口停損金額配置整數口, 以新台幣列損益/MDD,
    含資金(90萬,研究情境)/保證金(175,250, 2026-08-12 期交所值)/費用隨口數放大
註: 跳空濾網為任務書第二批明定項目, 但不在 research_spec.md 鎖定候選表內,
    故以附錄呈現、不參與勝出判準(spec 候選表跑後不增減)。
輸出: audit/out/research_R5_gap.csv, research_R6_sizing.csv"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from engine import max_drawdown, simulate_day_full  # noqa: E402
from run_research import (load_days, run_variant, signal, stats_row,  # noqa: E402
                          BASE_SL)


def full_trades(days, cost, slip=0.0):
    """與 run_research_supplement.full_trades 同義(該檔為無 main-guard 腳本,
    import 會整份重跑, 故在此複寫; 兩份以相同輸出交叉核對)。"""
    rows = []
    for d0 in days:
        if d0["status"] != "ok" or np.isnan(d0["s"]):
            continue
        dirn, at, bucket = signal(d0["s"])
        if dirn is None:
            continue
        ei = 0 if at == "open" else d0["ei_1000"]
        e = d0["e_open"] if at == "open" else d0["e_1000"]
        pnl, how, ex, xj = simulate_day_full(
            d0["op"], d0["hi"], d0["lo"], d0["cl"], ei, e, dirn, BASE_SL,
            cost=cost, slip=slip, fill_model="gap")
        rows.append(dict(date=d0["date"], bucket=bucket, entry=e, pnl=pnl,
                         how=how))
    return pd.DataFrame(rows)


def gap_map(era):
    """date -> 簽名跳空 (open_t/close_{t-1} - 1)。基準明定: 同盤別(日盤)前一
    交易日收盤 -> 當日日盤開盤。注意: MTX 有夜盤, 日盤開盤已內含夜盤走勢,
    此處量測的正是「訊號在可交易開盤前已被吸收多少」。"""
    if era == "modern":
        bars = pd.read_parquet("data/all_bars.parquet")
        bars = bars[bars["date"] >= "2023-01-01"]
    else:
        bars = pd.read_parquet("data/all_taiex_bars.parquet")
    out, prev_close = {}, None
    for date, g in bars.groupby("date"):
        if era == "modern":
            day = g.sort_index().between_time("08:45", "13:44")
        else:
            day = g.sort_values("minute")
        if not len(day):
            continue
        if prev_close:
            out[date] = float(day.iloc[0]["open"]) / prev_close - 1
        prev_close = float(day.iloc[-1]["close"])
    return out


rows = []
for era, cost in [("modern", 2.0), ("hist", 0.0)]:
    days = load_days(era)
    gm = gap_map(era)
    base_pm, base_tr = run_variant(days, cost)
    # ---- 5a. 吸收量化: gap ~ s 迴歸(訊號有效全日, 含空手桶) ----
    pairs = [(gm[d["date"]], d["s"]) for d in days
             if d["status"] == "ok" and not np.isnan(d["s"])
             and d["date"] in gm]
    gp = np.array([p[0] for p in pairs])
    sg = np.array([p[1] for p in pairs])
    beta = float(np.cov(gp, sg)[0, 1] / np.var(sg))
    corr = float(np.corrcoef(gp, sg)[0, 1])
    rows.append(dict(era=era, variant="absorption", n_days=len(gp),
                     note=f"beta={beta:.3f} corr={corr:.3f} "
                          f"median|gap|={np.median(np.abs(gp)):.3%}"))
    # ---- 5b. 跳空濾網: 訊號方向已跳 >= 門檻即放棄當日 ----
    dir_map = dict(zip(base_tr.date, base_tr.dir))
    for th in [0.005, 0.010]:
        pm = dict(base_pm)
        skipped = 0
        for d, dirn in dir_map.items():
            if d in gm and gm[d] * dirn >= th:
                pm[d] = 0.0
                skipped += 1
        r = stats_row(f"gapfilter_{th:.1%}", era, pm, base_pm)
        r["note"] = f"skipped={skipped}/{len(dir_map)}"
        rows.append(r)
    # ---- 5c. 延遲×滑價 合併敏感度(延遲已於 R5 單獨跑) ----
    for slip in [1.0, 2.0]:
        pm, _ = run_variant(days, cost, delay=True, slip=slip)
        rows.append(stats_row(f"delay1bar_slip{slip:.0f}", era, pm, base_pm))
pd.DataFrame(rows).to_csv("audit/out/research_R5_gap.csv", index=False)
print(pd.DataFrame(rows).to_string(index=False))

# ---- 6. 風險口數: 固定 1 口 vs 動態整數口(新台幣, 現代段) ----
# 情境參數(研究情境, 非推定實際資金): 資金 900,000 元(使用者 2026-08 對話指定的
# 試算基礎, 於此僅作情境); 保證金 175,250 元/口(2026-08-12 期交所值, 來源見
# docs/HANDOFF-AUDIT.md); 1 點=50 元; 費用 2 點/來回已含於 pnl 且隨口數等比放大。
CAP, MARGIN, PT = 900_000, 175_250, 50
days = load_days("modern")
tr = full_trades(days, 2.0).sort_values("date")
max_lots_margin = int(CAP // MARGIN)
r6 = []
for name, lots_fn in [
        ("fixed_1lot", lambda e: 1),
        ("risk1pct", lambda e: min(int((CAP * 0.01) // (e * BASE_SL * PT)),
                                   max_lots_margin)),
        ("risk2pct", lambda e: min(int((CAP * 0.02) // (e * BASE_SL * PT)),
                                   max_lots_margin))]:
    lots = tr.entry.map(lots_fn)
    ntd = tr.pnl * PT * lots
    active = int((lots > 0).sum())
    r6.append(dict(
        scenario=name, n_trades=len(tr), n_active=active,
        zero_lot_days=len(tr) - active,
        avg_lots=round(float(lots.mean()), 2),
        max_lots=int(lots.max()),
        total_ntd=round(float(ntd.sum()), 0),
        mdd_ntd=round(max_drawdown(ntd.tolist()), 0),
        mdd_pct_cap=f"{max_drawdown(ntd.tolist())/CAP:.1%}",
        ret_pct_cap=f"{ntd.sum()/CAP:.1%}"))
pd.DataFrame(r6).to_csv("audit/out/research_R6_sizing.csv", index=False)
print()
print(f"R6 情境: 資金 {CAP:,}(研究情境) 保證金 {MARGIN:,}/口 "
      f"(2026-08-12) 保證金上限 {max_lots_margin} 口; 每口停損風險約 "
      f"{tr.entry.mean()*BASE_SL*PT:,.0f} 元")
print(pd.DataFrame(r6).to_string(index=False))
