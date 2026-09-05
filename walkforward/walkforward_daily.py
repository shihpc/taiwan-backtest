#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Playbook v3 前推對帳 — 每日模擬記帳
  規則: v3-SL (2026-09-04 定版, 不得回頭改; 見 ../README.md 停損/停利括號研究)
  = v3 方向規則 + 停損 0.75%(進場價計, 觸價出場) + 未觸損收盤平, 無停利
  舊版 v3(無停損)帳冊封存於 ledger_v3_nostop.csv
  原 v3 定版註記:
    前晚費半(^SOX)  大跌<-2%: 空手 | 跌-2~-1%: 08:45空->13:44 | 小跌-1~0: 空手
                   小漲0~1%: 08:45多->13:44 | 漲1~2%: 08:45多->13:44 | 大漲>2%: 10:00空->13:44
  成本 2 點。逐日 append walkforward/ledger.csv, 冪等(同日已記帳即跳過)。
  2026-09-05 口徑統一: 收盤出場=13:44 最後成交(<=13:44:59), 不含 13:45 定盤 tick
  (2026-09-03/04 兩列為舊 13:45 口徑, 不回改; 稽核 AUDIT-REPORT P1 節)。
  目標日: 台北時間 hour<12 回推一天(防 cron 延遲跨午夜, 同 taiwan-flows target_trading_day)。
  資料未落地/非交易日 -> 正常結束(exit 0), 由下一班或隔日補。
"""
import csv
import os
import sys
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")
COST = 2.0
SL_PCT = 0.0075   # v3-SL 停損(進場價比例)
HERE = Path(__file__).parent
LEDGER = HERE / "ledger.csv"
COLS = ["date", "sox_date", "sox_ret", "bucket", "action",
        "entry_time", "entry_px", "exit_px", "how", "pnl_sim", "cum_pnl"]

def api_get(params):
    p = dict(params, token=TOKEN)
    r = requests.get(API, params=p, timeout=90)
    j = r.json()
    if j.get("status") != 200:
        sys.exit(f"API 失敗: {j.get('msg')}")
    return j.get("data", [])

def main():
    if not TOKEN:
        sys.exit("需要 FINMIND_TOKEN")
    now = dt.datetime.now(ZoneInfo("Asia/Taipei"))
    target = (now - dt.timedelta(hours=12)).date()  # hour<12 -> 前一天
    if target.weekday() >= 5:
        print(f"{target} 週末, 跳過"); return
    tstr = str(target)

    rows = []
    if LEDGER.exists():
        rows = list(csv.DictReader(open(LEDGER)))
        if any(r["date"] == tstr for r in rows):
            print(f"{tstr} 已記帳, 跳過"); return

    # 前晚費半: 取 < target 的最近兩個美股日算報酬
    sox = api_get(dict(dataset="USStockPrice", data_id="^SOX",
                       start_date=str(target - dt.timedelta(days=12)),
                       end_date=tstr))
    sox = [r for r in sox if r["date"] < tstr]
    if len(sox) < 2:
        sys.exit(f"費半資料不足 ({len(sox)} 筆)")
    sox_date = sox[-1]["date"]
    sox_ret = sox[-1]["Close"] / sox[-2]["Close"] - 1

    if sox_ret < -0.02:
        bucket, action = "大跌<-2%", "空手"
    elif sox_ret < -0.01:
        bucket, action = "跌-2~-1%", "空0845"
    elif sox_ret < 0:
        bucket, action = "小跌-1~0", "空手"
    elif sox_ret < 0.01:
        bucket, action = "小漲0~1%", "多0845"
    elif sox_ret < 0.02:
        bucket, action = "漲1~2%", "多0845"
    else:
        bucket, action = "大漲>2%", "空1000"

    entry_t, entry_px, exit_px, pnl, how = "", "", "", 0.0, ""
    if action != "空手":
        tick = api_get(dict(dataset="TaiwanFuturesTick", data_id="MTX",
                            start_date=tstr))
        if not tick:
            print(f"{tstr} 無 tick 資料(未落地或非交易日), 本班不記帳"); return
        df = pd.DataFrame(tick)
        df["contract_date"] = df["contract_date"].astype(str)
        df = df[~df["contract_date"].str.contains("/")]
        near = df.groupby("contract_date")["volume"].sum().idxmax()
        df = df[df["contract_date"] == near].copy()
        df["t"] = df["date"].astype(str).str.slice(11, 19)
        # 收盤口徑統一 13:44(2026-09-05 使用者裁定): 不含 13:45 定盤 tick,
        # 與回測主張 A/B(a19)口徑一致; 帳冊既有歷史列(13:45 口徑)不回改。
        day = df[(df["t"] >= "08:45:00") & (df["t"] <= "13:44:59")]
        if day.empty:
            print(f"{tstr} 日盤 tick 空, 本班不記帳"); return
        day = day.sort_values("t")
        px = day["price"].astype(float)
        o0845 = float(px.iloc[0])
        after10 = day[day["t"] >= "10:00:00"]
        o10 = float(after10["price"].astype(float).iloc[0]) if len(after10) else o0845
        c1344 = float(px.iloc[-1])
        if action == "空0845":
            entry_t, entry_px, sgn = "08:45", o0845, -1
            seg = day
        elif action == "多0845":
            entry_t, entry_px, sgn = "08:45", o0845, 1
            seg = day
        else:  # 空1000
            entry_t, entry_px, sgn = "10:00", o10, -1
            seg = day[day["t"] >= "10:00:00"]
        # v3-SL: 進場後依時間序掃停損 0.75%
        sl_px = entry_px * SL_PCT
        px_seq = seg["price"].astype(float).to_numpy()
        adverse = (px_seq - entry_px) * -sgn
        hit = (adverse >= sl_px).nonzero()[0]
        if len(hit):
            exit_px = entry_px - sgn * sl_px
            pnl = -sl_px - COST
            how = "stop"
        else:
            exit_px = c1344
            pnl = (exit_px - entry_px) * sgn - COST
            how = "close"

    cum = (float(rows[-1]["cum_pnl"]) if rows else 0.0) + pnl
    new = not LEDGER.exists()
    with open(LEDGER, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLS)
        w.writerow([tstr, sox_date, round(sox_ret, 5), bucket, action,
                    entry_t, entry_px, round(exit_px, 1) if exit_px != "" else "",
                    how, round(pnl, 1), round(cum, 1)])
    n_act = sum(1 for r in rows if r["action"] != "空手") + (action != "空手")
    print(f"{tstr} 記帳: {bucket} -> {action}, pnl={pnl:+.1f}, 累積={cum:+.1f} 點 "
          f"(出勤 {n_act} 日)")
    # 對帳警戒: 累積回落超過回測 MDD (-2044) 即在 log 標紅
    vals = [0.0] + [float(r["cum_pnl"]) for r in rows] + [cum]
    peak, mdd = -1e9, 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    print(f"目前回落 {mdd:+.1f} 點 (回測 MDD -2044; 超過即停機檢討)")
    if mdd < -2044:
        print("::warning::前推回落已超過回測 MDD, 依紀律應停機檢討")

if __name__ == "__main__":
    main()
