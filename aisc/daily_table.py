# -*- coding: utf-8 -*-
"""Phase 0 每日描述表：117 檔的收盤、ext、r5、MA60 上下、R2 濾網狀態（規格 §3 末段、§9 Phase 0）。

純描述、不下單、不產委託單。R1 前 10 名只標「候選排序（待回測）」，供日後與回測對照。

日期口徑（2026-10-13 修正日期混用）：
- 各市場「資料日」＝該市場個股最新 date 的最大值。台股個股是 TaiwanStockPriceAdj（常比大盤晚一天落地），
  大盤 TAIEX 是 TaiwanStockPrice（當天就有），所以大盤序列一律先截到 ≤ 該市場資料日再算 MA60／R2，
  R2 才與個股指標同一天（回測 §8 也是訊號日 t 看大盤 t）。
- 檔名日期＝各市場資料日的較晚者（不覆寫舊檔）；兩市場資料日不同時，md／LINE 逐市場寫明。
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
    dates = snap["date"].dropna()
    data_date = str(dates.max()) if not dates.empty else None
    # 大盤截到 ≤ 個股資料日：R2／MA60 與個股指標同一天，不拿比個股新的大盤值
    if data_date is not None and not bench.empty:
        bench = bench[bench["date"] <= data_date]
    r2 = I.r2_filter(bench) if not bench.empty else pd.Series(dtype=bool)
    bench_last = bench.iloc[-1] if not bench.empty else None
    meta = {"market": market, "data_date": data_date,
            "n_stale": int((dates < data_date).sum()) if data_date else 0,
            "bench_date": None, "bench_close": None, "bench_ma60": None, "r2_off": None}
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


def asof_date(snaps: list[tuple[pd.DataFrame, dict]]) -> str | None:
    """檔名日期＝各市場資料日的較晚者；全無資料回 None。"""
    ds = [meta["data_date"] for _, meta in snaps if meta.get("data_date")]
    return max(ds) if ds else None


def dates_line(snaps: list[tuple[pd.DataFrame, dict]]) -> str:
    return "｜".join(f"{meta['market']} {meta.get('data_date') or '—'}" for _, meta in snaps)


def stale_note(meta: dict) -> str:
    return f"（{meta['n_stale']} 檔個股日期早於資料日）" if meta.get("n_stale") else ""


def pool_line(uni: dict | None) -> str:
    """候選池版本：台股每月 11 號起換池（universe_refresh），美股凍結。"""
    if not uni:
        return ""
    tw_at = uni.get("tw_refreshed_at") or uni.get("frozen_at")
    src = next((c.get("source", {}).get("date") for c in reversed(uni.get("changes", [])) if c.get("source")), None)
    tw = f"TW {len(uni['TW'])} 檔（" + (f"{tw_at} 換池，依 screen {src}" if src else f"{tw_at} 初始凍結") + "）"
    return f"候選池 {uni.get('version', '—')}：{tw}｜US {len(uni['US'])} 檔（{uni.get('frozen_at')} 凍結）"


def render_md(snaps: list[tuple[pd.DataFrame, dict]], asof: str, uni: dict | None = None) -> str:
    L = [f"# AI 供應鏈每日描述表 {asof}", "",
         f"資料日：{dates_line(snaps)}（檔名取各市場資料日較晚者；大盤與 R2 一律取各市場自己的資料日）", ""]
    if uni:
        L += [pool_line(uni), ""]
    L += [
         "純描述欄位（規格 v2 §3）；R1 排名為候選排序、**待回測、不據此下單**。所有判讀屬 AI 研判，非投資保證。", ""]
    for snap, meta in snaps:
        m = meta["market"]
        bench = "—" if meta["bench_date"] is None else (
            f"{meta['bench_close']} vs MA60 {meta['bench_ma60']}（{meta['bench_date']}）→ "
            + ("**R2 濾網啟動：不開新倉**" if meta["r2_off"] else "R2 通過"))
        L += [f"## {m}（{len(snap)} 檔）", "", f"資料日：{meta.get('data_date') or '—'}{stale_note(meta)}", "",
              f"大盤：{bench}", ""]
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


def render_line(snaps: list[tuple[pd.DataFrame, dict]], asof: str, uni: dict | None = None) -> str:
    L = [f"【AI供應鏈 每日表 {asof}】描述用，不下單"]
    if uni:
        L.append(pool_line(uni))
    for snap, meta in snaps:
        m = meta["market"]
        r2 = "—" if meta["r2_off"] is None else ("R2 關：不開新倉" if meta["r2_off"] else "R2 開")
        L.append(f"■ {m} 資料日 {meta.get('data_date') or '—'}{stale_note(meta)}")
        L.append(f"大盤 {meta['bench_close']}／MA60 {meta['bench_ma60']} {r2}")
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
    asof = asof_date(snaps) or dt.date.today().isoformat()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    pd.concat([s for s, _ in snaps]).to_csv(out / f"{asof}.csv", index=False)
    (out / f"{asof}.md").write_text(render_md(snaps, asof, uni), encoding="utf-8")
    print(render_line(snaps, asof, uni))
    print(f"寫入 {out / (asof + '.csv')}")
    if a.push:
        from . import notify
        print("LINE push:", notify.push_text(render_line(snaps, asof, uni)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
