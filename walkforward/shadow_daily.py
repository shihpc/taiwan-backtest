#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""影子對照帳冊 — 每日模擬記帳（規格見 SHADOW-SPEC.md, 先 commit 後執行, 不回改）
  影子 A: v3-SL + 1R 保本            -> ledger_shadow_1rbe.csv
  影子 B: v3-SL + 1R 保本 + 時間停損 -> ledger_shadow_1rbe_ts.csv
  訊號/進場/成本/口徑與 walkforward_daily.py 逐字同語意; 正式帳冊完全不碰。
  掛在 walkforward.yml 正式記帳 commit 之後; 冪等(同日已記帳跳過)。"""
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
SL_PCT = 0.0075
BE_OFFSET = 2.0        # 保本價=entry+方向*2(涵蓋成本)
TS_AFTER_MIN = 60      # 進場後滿 60 分鐘起檢查時間停損
TS_MFE_R = 0.5         # 累積最大浮盈門檻(單位 R)
HERE = Path(__file__).parent
COLS = ["date", "sox_date", "sox_ret", "bucket", "action",
        "entry_time", "entry_px", "exit_px", "how", "pnl_sim", "cum_pnl"]
LEDGERS = {"A": HERE / "ledger_shadow_1rbe.csv",
           "B": HERE / "ledger_shadow_1rbe_ts.csv"}


def simulate_shadow(times, prices, entry_i, sgn, variant):
    """單日影子模擬(純函式, 供測試)。times: 'HH:MM:SS' list(升冪, 日盤已過濾),
    prices: float list, entry_i: 進場 tick 序號, sgn: 1/-1, variant: 'A'/'B'。
    回傳 (pnl, how, exit_px)。進場價=prices[entry_i]。"""
    entry_px = prices[entry_i]
    r_amt = entry_px * SL_PCT
    be_level = entry_px + sgn * BE_OFFSET
    armed_minute = None      # 保本武裝 tick 所在分鐘('HH:MM'); 次一分鐘起生效
    entry_minute = times[entry_i][:5]
    # 時間停損狀態(variant B): 逐分鐘結算
    minute_mfe = {}          # 'HH:MM' -> 該分鐘內最有利波幅
    minute_last = {}         # 'HH:MM' -> 該分鐘最後價
    ts_pending = False       # 已觸發時間停損, 等下一有成交分鐘首筆
    cum_mfe = 0.0
    prev_minute = None

    def minutes_since_entry(m):
        h1, m1 = int(entry_minute[:2]), int(entry_minute[3:5])
        h2, m2 = int(m[:2]), int(m[3:5])
        return (h2 * 60 + m2) - (h1 * 60 + m1)

    for j in range(entry_i, len(prices)):
        p, m = prices[j], times[j][:5]
        # ---- 分鐘邊界: 先結算上一分鐘(時間停損判定), 再處理本 tick ----
        if prev_minute is not None and m != prev_minute:
            cum_mfe = max(cum_mfe, minute_mfe.get(prev_minute, -1e18))
            if variant == "B" and not ts_pending \
                    and minutes_since_entry(prev_minute) >= TS_AFTER_MIN:
                net_eod = (minute_last[prev_minute] - entry_px) * sgn
                if cum_mfe < TS_MFE_R * r_amt and net_eod < 0:
                    ts_pending = True
            if ts_pending:
                # 下一有成交分鐘首筆 = 本 tick
                return (p - entry_px) * sgn - COST, "time_stop", p
        prev_minute = m
        fav = (p - entry_px) * sgn
        minute_mfe[m] = max(minute_mfe.get(m, -1e18), fav)
        minute_last[m] = p
        # ---- 保本停損(武裝且已過武裝分鐘) ----
        if armed_minute is not None and m != armed_minute \
                and (p - be_level) * sgn <= 0:
            return BE_OFFSET - COST, "be_stop", be_level
        # ---- 基礎停損 0.75%(未被保本位取代前恆在; 保本生效後保本位較緊, 先觸) ----
        if -fav >= r_amt:
            return -r_amt - COST, "stop", entry_px - sgn * r_amt
        # ---- 保本武裝: 首次有利波幅 >= 1R ----
        if armed_minute is None and fav >= r_amt:
            armed_minute = m
    close_px = prices[-1]
    return (close_px - entry_px) * sgn - COST, "close", close_px


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
    target = (now - dt.timedelta(hours=12)).date()
    if target.weekday() >= 5:
        print(f"{target} 週末, 跳過"); return
    tstr = str(target)

    ledger_rows = {}
    todo = []
    for k, path in LEDGERS.items():
        rows = list(csv.DictReader(open(path))) if path.exists() else []
        ledger_rows[k] = rows
        if not any(r["date"] == tstr for r in rows):
            todo.append(k)
    if not todo:
        print(f"{tstr} 影子皆已記帳, 跳過"); return

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

    results = {}   # k -> (entry_t, entry_px, exit_px, pnl, how)
    if action == "空手":
        for k in todo:
            results[k] = ("", "", "", 0.0, "")
    else:
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
        day = df[(df["t"] >= "08:45:00") & (df["t"] <= "13:44:59")]
        if day.empty:
            print(f"{tstr} 日盤 tick 空, 本班不記帳"); return
        day = day.sort_values("t")
        times = day["t"].tolist()
        prices = day["price"].astype(float).tolist()
        if action == "空1000":
            idx = next((i for i, t in enumerate(times) if t >= "10:00:00"), 0)
            entry_t, sgn = "10:00", -1
        else:
            idx = 0
            entry_t, sgn = "08:45", (1 if action.startswith("多") else -1)
        for k in todo:
            pnl, how, exit_px = simulate_shadow(times, prices, idx, sgn, k)
            results[k] = (entry_t, prices[idx], exit_px, pnl, how)

    for k in todo:
        entry_t, entry_px, exit_px, pnl, how = results[k]
        rows = ledger_rows[k]
        cum = (float(rows[-1]["cum_pnl"]) if rows else 0.0) + pnl
        new = not LEDGERS[k].exists()
        with open(LEDGERS[k], "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLS)
            w.writerow([tstr, sox_date, round(sox_ret, 5), bucket, action,
                        entry_t, entry_px,
                        round(exit_px, 1) if exit_px != "" else "",
                        how, round(pnl, 1), round(cum, 1)])
        print(f"{tstr} 影子{k} 記帳: {bucket} -> {action}, "
              f"pnl={pnl:+.1f}, how={how or '-'}, 累積={cum:+.1f}")


if __name__ == "__main__":
    main()
