#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0-3 選約時序稽核: 回測建檔用「當日全日量最大 contract_date」選近月(前視),
以 FinMind TaiwanFuturesDaily(每合約日量)重建:
  rule_hindsight = 當日量最大(建檔實際用) vs rule_prior = 前一交易日量最大(進場時可知)
輸出 audit/out/contract_selection_audit.csv + 差異日清單
需 FINMIND_TOKEN(一次 range 請求, 非 tick)。
"""
import os
import sys

import pandas as pd
import requests

TOKEN = os.environ.get("FINMIND_TOKEN", "")
if not TOKEN:
    sys.exit("需要 FINMIND_TOKEN")

r = requests.get("https://api.finmindtrade.com/api/v4/data", params=dict(
    dataset="TaiwanFuturesDaily", data_id="MTX",
    start_date="2023-08-10", end_date="2026-08-20", token=TOKEN),
    timeout=120).json()
if r.get("status") != 200:
    sys.exit(f"API 失敗: {r.get('msg')}")
df = pd.DataFrame(r["data"])
df = df[~df["contract_date"].astype(str).str.contains("/")]
piv = df.pivot_table(index="date", columns="contract_date",
                     values="volume", aggfunc="sum").fillna(0)
hind = piv.idxmax(axis=1)                      # 全日量最大(回測實際用, 前視)
prior = hind.shift(1)                          # 前一交易日量最大(事前可知)
out = pd.DataFrame(dict(hindsight=hind, prior_day=prior)).dropna()
out["differs"] = out.hindsight != out.prior_day
out.to_csv("audit/out/contract_selection_audit.csv")
diff = out[out.differs]
print(f"交易日 {len(out)}, 兩規則不同日 {len(diff)} ({len(diff)/len(out):.1%})")
print("差異日(=實際換月日, 前視規則提早一天換):")
print(diff.to_string())
