#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""資料品質稽核: bar 覆蓋/OHLC 合法性/重複/必要時點缺漏 + SOX 對齊。免 token。
輸出 audit/out/bars_quality_{modern,hist}.csv, sox_quality.txt"""
import numpy as np
import pandas as pd

def audit_modern():
    bars = pd.read_parquet("data/all_bars.parquet")
    rows = []
    for date, g in bars.groupby("date"):
        g = g.sort_index()
        t = g.index.time.astype(str) if hasattr(g.index.time, "astype") else [
            str(x) for x in g.index.time]
        tset = set(str(x)[:5] for x in g.index.time)
        bad_ohlc = int(((g.high < g.low) | (g.high < g.open) |
                        (g.high < g.close) | (g.low > g.open) |
                        (g.low > g.close)).sum())
        rows.append(dict(
            date=date, n_bars=len(g),
            dup_ts=int(g.index.duplicated().sum()),
            bad_ohlc=bad_ohlc,
            has_0845="08:45" in tset, has_1000="10:00" in tset,
            has_1344="13:44" in tset, has_1345="13:45" in tset,
            first=str(g.index[0].time())[:5], last=str(g.index[-1].time())[:5]))
    df = pd.DataFrame(rows)
    df.to_csv("audit/out/bars_quality_modern.csv", index=False)
    print("== modern (all_bars) ==")
    print(f"  天數 {len(df)}, dup_ts>0: {(df.dup_ts>0).sum()}, "
          f"bad_ohlc>0: {(df.bad_ohlc>0).sum()}")
    for col in ["has_0845", "has_1000", "has_1344", "has_1345"]:
        miss = df[~df[col]]
        print(f"  缺 {col[4:]}: {len(miss)} 天"
              + (f" -> {miss.date.tolist()[:6]}" if len(miss) else ""))
    short = df[df.n_bars < 200]
    print(f"  n_bars<200(a19 排除): {len(short)} 天 -> {short.date.tolist()[:8]}")

def audit_hist():
    allb = pd.read_parquet("data/all_taiex_bars.parquet")
    rows = []
    for date, g in allb.groupby("date"):
        g = g.sort_values("minute")
        m = g.minute.str[:5]
        bad_ohlc = int(((g.high < g.low) | (g.high < g.open) |
                        (g.high < g.close) | (g.low > g.open) |
                        (g.low > g.close)).sum())
        rows.append(dict(date=date, n_bars=len(g),
                         dup_ts=int(g.minute.duplicated().sum()),
                         bad_ohlc=bad_ohlc,
                         has_0900=(m == "09:00").any(),
                         has_1000=(m == "10:00").any(),
                         has_1330=(m == "13:30").any(),
                         first=m.iloc[0], last=m.iloc[-1]))
    df = pd.DataFrame(rows)
    df.to_csv("audit/out/bars_quality_hist.csv", index=False)
    print("== hist (all_taiex_bars) ==")
    print(f"  天數 {len(df)}, dup_ts>0: {(df.dup_ts>0).sum()}, "
          f"bad_ohlc>0: {(df.bad_ohlc>0).sum()}")
    for col in ["has_0900", "has_1000", "has_1330"]:
        miss = df[~df[col]]
        print(f"  缺 {col[4:]}: {len(miss)} 天"
              + (f" -> {miss.date.tolist()[:6]}" if len(miss) else ""))
    short = df[df.n_bars < 200]
    print(f"  n_bars<200(排除): {len(short)} 天 -> {short.date.tolist()[:8]}")
    odd = df[(df.first_ if hasattr(df, 'first_') else df['first']) != "09:00"]
    print(f"  首bar非09:00: {len(odd)} 天 -> {odd.date.tolist()[:6]}")

def audit_sox():
    print("== SOX 對齊 ==")
    for path, tw_path, era in [
            ("data/us_sox.parquet", "data/all_bars.parquet", "modern"),
            ("data/us_sox_long.parquet", "data/all_taiex_bars.parquet", "hist")]:
        s = pd.read_parquet(path).sort_values("date")
        dup = int(s.date.duplicated().sum())
        na = int(s.Close.isna().sum())
        zero = int((s.Close <= 0).sum())
        sd = s.date.to_numpy()
        tw = sorted(pd.read_parquet(tw_path)["date"].unique())
        lags = []
        for d in tw:
            ix = np.searchsorted(sd, d) - 1
            if ix >= 0:
                lag = (pd.Timestamp(d) - pd.Timestamp(sd[ix])).days
                lags.append((d, sd[ix], lag))
        lagdf = pd.DataFrame(lags, columns=["tw", "us", "days"])
        stale = lagdf[lagdf.days > 4]
        strict = int((lagdf.us >= lagdf.tw).sum())
        print(f"  {era}: 重複日 {dup}, Close NaN {na}, Close<=0 {zero}, "
              f"對齊違反嚴格早於 {strict} 天, 落後>4天 {len(stale)} 天"
              + (f" -> {stale.tw.tolist()[:5]}" if len(stale) else ""))

if __name__ == "__main__":
    audit_modern()
    audit_hist()
    audit_sox()
