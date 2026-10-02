# -*- coding: utf-8 -*-
"""共用設定與路徑（規格 v2 §2／§3／§5／§8 的常數，回測前寫死；要改＝v3）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_DIR = PKG_DIR.parent
UNIVERSE_PATH = PKG_DIR / "universe.json"
PRICE_CACHE_DIR = REPO_DIR / "data" / "aisc" / "prices"      # 不進 git（data/aisc/.gitignore）
OUTPUT_DIR = REPO_DIR / "output" / "aisc"                    # 每日表與回測報告（進 git）
# 私人帳務（IBKR Flex 報表、券商庫存）一律放 repo 外；預設 ~/.aisc，可用環境變數覆寫
PRIVATE_DIR = Path(os.environ.get("AISC_PRIVATE_DIR", Path.home() / ".aisc"))

# ---- 規格 §3 選股規則常數 ----
MA_SHORT = 20          # ext 的 MA
MA_LONG = 60           # 多頭門檻與 R2 大盤濾網的 MA
ATR_N = 14
R5_N = 5
R20_N = 20
TOP_N = 10             # R1 取前 10
LIQ_N = 20             # R3 近 20 日平均成交金額
LIQ_MIN = {"TW": 3e8, "US": 50e6}   # R3 門檻：台股 NT$3 億、美股 US$50M（可調但要記錄）

# ---- 規格 §4／§8 進出場與回測 ----
HOLD_DAYS = 60         # 持有 60 個交易日後收盤出場（H=60，與 v1 一致）
SAMPLE_START = "2021-01-04"
OOS_START = "2026-07-09"            # 2026-07-08 以前樣本內、之後樣本外
STOP_LOSS_PCT = 0.15                # S5 對照用：收盤跌破進場價 15% 隔日出場（不當關卡）
# 成本（§8 設定）：台股手續費 0.1425%×6 折 雙邊 ＋ 證交稅 0.3% 賣出；美股每股 US$0.005、最低 US$1
TW_FEE_RATE = 0.001425 * 0.6
TW_TAX_RATE = 0.003
US_FEE_PER_SHARE = 0.005
US_FEE_MIN = 1.0
# 回測部位：等權（每檔＝總資金 ÷ 持股數上限，§5），美股成本要股數故需名目資金
BT_CAPITAL = {"TW": 10_000_000.0, "US": 300_000.0}
MIN_YEAR_SAMPLES = 50               # 年份切片納入通過條件的最低樣本數
YEAR_PASS_FRAC = 2 / 3

# ---- FinMind 資料集 ----
FM_API = "https://api.finmindtrade.com/api/v4/data"
FM_DATASET = {"TW": "TaiwanStockPriceAdj", "US": "USStockPrice"}


def load_universe(path: Path = UNIVERSE_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def universe_codes(uni: dict, market: str) -> list[str]:
    return [x["code"] for x in uni[market]]


def universe_names(uni: dict) -> dict[tuple[str, str], str]:
    return {(m, x["code"]): x["name"] for m in ("TW", "US") for x in uni[m]}
