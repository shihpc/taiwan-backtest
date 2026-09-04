#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓 TAIEX 分K 完整 OHLC (2005-2022) 逐日 parquet 快取 -> data/taiex_bars/"""
import os, sys, time
from pathlib import Path
import pandas as pd, requests

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")
if not TOKEN: sys.exit("需要 FINMIND_TOKEN")
BAR_DIR = Path("data/taiex_bars"); BAR_DIR.mkdir(parents=True, exist_ok=True)

def api_get(params, retries=6):
    p = dict(params, token=TOKEN)
    for i in range(retries):
        try:
            j = requests.get(API, params=p, timeout=90).json()
        except Exception as e:
            print(f"  [warn] {e}"); time.sleep(min(60, 3*2**i)); continue
        if j.get("status") == 200: return j.get("data", [])
        print(f"  [warn] msg={j.get('msg')}"); time.sleep(min(120, 5*2**i))
    raise RuntimeError(f"API 失敗: {params}")

dates = sorted(pd.read_csv("data/taiex_daily_agg.csv").date)
todo = [d for d in dates if not (BAR_DIR/f"{d}.parquet").exists()]
print(f"共 {len(dates)} 天, 待抓 {len(todo)}")
for i, d in enumerate(todo, 1):
    rows = api_get(dict(dataset="TaiwanStockKBar", data_id="TAIEX", start_date=d))
    if rows:
        pd.DataFrame(rows)[["date","minute","open","high","low","close"]].to_parquet(BAR_DIR/f"{d}.parquet")
    if i % 200 == 0: print(f"  進度 {i}/{len(todo)}")
    time.sleep(0.25)
print("完成")
