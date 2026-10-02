# -*- coding: utf-8 -*-
"""Phase 0 每日描述表：117 檔的收盤、ext、r5、MA60 上下、R2 濾網狀態（規格 §3 末段、§9 Phase 0）。

純描述、不下單、不產委託單。R1 前 10 名只標「候選排序（待回測）」，供日後與回測對照。
用法：
  python3 -m aisc.daily_table                 # 抓最新價、寫 output/aisc/daily/<date>.csv 與 .md
  python3 -m aisc.daily_table --push          # 另推 LINE 簡表
  python3 -m aisc.daily_table --offline       # 只讀快取不打 FinMind
  python3 -m aisc.daily_table --market TW     # 只跑一個市場
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

from . import config as C
from . import data as D
from . import indicators as I


def snapshot_market(market: str, uni: dict, prices: dict, bench: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    names = C.universe_names(uni)
    r2 = I.r2_filter(bench) if not bench.empty else pd.Series(dtype=bool)
    bench_last = bench.iloc[-1] if not bench.empty else None
    rows = []
    for code in C.universe_codes(uni, market):
        df = prices.get((market, code))
        if df is None or df.empty:
            rows.append({"market": market, "code": code, "name": names[(market, code)], "date": None,
                         "note": "無價格資料"})
            continue
        f = I.add_features(df).iloc[-1]
        rows.append({
            "market": market, "code": code, "name": names[(market, code)], "date": f["date"],
            "close": round(float(f["close"]), 2),
            "ext": None if pd.isna(f["ext"]) else round(float(f["ext"]), 2),
            "r5": None if pd.isna(f["r5"]) else round(float(f["r5"]) * 100, 2),
            "r20": None if pd.isna(f["r20"]) else round(float(f["r20"]) * 100, 2),
            "above60": bool(f["above60"]) if not pd.isna(f["ma60"]) else None,
            "slope60": None if pd.isna(f["slope60"]) else round(float(f["slope60"]), 2),
            "liq20": None if pd.isna(f["liq20"]) else float(f["liq20"]),
            "r3_pass": bool(f["liq20"] >= C.LIQ_MIN[market]) if not pd.isna(f["liq20"]) else None,
            "note": "",
        })
    snap = pd.DataFrame(rows)
    meta = {"market": market, "bench_date": None, "bench_close": None, "bench_ma60": None, "r2_off": None}
    if bench_last is not None:
        bma = bench["close"].rolling(C.MA_LONG).mean().iloc[-1]
        meta.update(bench_date=bench_last["date"], bench_close=round(float(bench_last["close"]), 2),
                    bench_ma60=None if pd.isna(bma) else round(float(bma), 2),
                    r2_off=bool(r2.iloc[-1]) if len(r2) else None)
    valid = snap.dropna(subset=["ext"]) if "ext" in snap else snap.iloc[0:0]
    if not valid.empty:
        ranked = I.rank_candidates(valid, market, "ext")
        snap["r1_rank"] = snap["code"].map(dict(zip(ranked["code"], ranked["rank"])))
    else:
        snap["r1_rank"] = None
    return snap, meta


def render_md(snaps: list[tuple[pd.DataFrame, dict]], asof: str) -> str:
    L = [f"# AI 供應鏈每日描述表 {asof}", "",
         "純描述欄位（規格 v2 §3）；R1 排名為候選排序、**待回測、不據此下單**。所有判讀屬 AI 研判，非投資保證。", ""]
    for snap, meta in snaps:
        m = meta["market"]
        bench = "—" if meta["bench_date"] is None else (
            f"{meta['bench_close']} vs MA60 {meta['bench_ma60']}（{meta['bench_date']}）→ "
            + ("**R2 濾網啟動：不開新倉**" if meta["r2_off"] else "R2 通過"))
        L += [f"## {m}（{len(snap)} 檔）", "", f"大盤：{bench}", ""]
        top = snap[snap["r1_rank"].notna()].sort_values("r1_rank")
        L += ["R1 候選排序（C>MA60 且 R3 通過，依 ext 高→低，前 10）：", ""]
        L += ["| # | 代號 | 名稱 | 收盤 | ext | r5% | r20% |", "|---|---|---|---|---|---|---|"]
        for _, r in top.iterrows():
            L.append(f"| {int(r['r1_rank'])} | {r['code']} | {r['name']} | {r['close']} | {r['ext']} | {r['r5']} | {r['r20']} |")
        L += ["", "全表：", "", "| 代號 | 名稱 | 日期 | 收盤 | ext | r5% | MA60上 | R3 |", "|---|---|---|---|---|---|---|---|"]
        for _, r in snap.iterrows():
            a = {True: "上", False: "下", None: "—"}.get(r.get("above60"), "—")
            p = {True: "✓", False: "✗", None: "—"}.get(r.get("r3_pass"), "—")
            L.append(f"| {r['code']} | {r['name']} | {r.get('date') or '—'} | {r.get('close', '—')} | {r.get('ext', '—')} | {r.get('r5', '—')} | {a} | {p} |")
        L.append("")
    return "\n".join(L)


def render_line(snaps: list[tuple[pd.DataFrame, dict]], asof: str) -> str:
    L = [f"【AI供應鏈 每日表 {asof}】描述用，不下單"]
    for snap, meta in snaps:
        m = meta["market"]
        r2 = "—" if meta["r2_off"] is None else ("R2 關：不開新倉" if meta["r2_off"] else "R2 開")
        L.append(f"■ {m} 大盤 {meta['bench_close']}／MA60 {meta['bench_ma60']} {r2}")
        top = snap[snap["r1_rank"].notna()].sort_values("r1_rank")
        for _, r in top.iterrows():
            L.append(f"{int(r['r1_rank'])}. {r['code']} {r['name']} ext{r['ext']} r5 {r['r5']}%")
        n_missing = int(snap["date"].isna().sum())
        if n_missing:
            L.append(f"（{n_missing} 檔無資料）")
    L.append("R1 待回測；AI 研判非保證")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["TW", "US"], action="append")
    ap.add_argument("--offline", action="store_true", help="只讀快取")
    ap.add_argument("--push", action="store_true", help="推 LINE")
    ap.add_argument("--out", default=str(C.OUTPUT_DIR / "daily"))
    a = ap.parse_args(argv)
    markets = tuple(a.market) if a.market else ("TW", "US")
    uni = C.load_universe()
    snaps = []
    for m in markets:
        prices = D.load_all(uni, (m,), refresh=not a.offline)
        bench = D.load_benchmark(m, uni, refresh=not a.offline)
        snaps.append(snapshot_market(m, uni, prices, bench))
    dates = [s["date"].dropna().max() for s, _ in snaps if s["date"].notna().any()]
    asof = max(dates) if dates else dt.date.today().isoformat()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pd.concat([s for s, _ in snaps]).to_csv(out / f"{asof}.csv", index=False)
    (out / f"{asof}.md").write_text(render_md(snaps, asof), encoding="utf-8")
    print(render_line(snaps, asof))
    print(f"寫入 {out / (asof + '.csv')}")
    if a.push:
        from . import notify
        print("LINE push:", notify.push_text(render_line(snaps, asof)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
