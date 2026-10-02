# -*- coding: utf-8 -*-
"""指標層：純函式，只用當日以前資料（無前視）。規格 v2 §3 定義。

ext    = (C − MA20) ／ ATR14           （ATR14＝真實波幅 14 日簡單平均）
r5     = C ／ C₋₅ − 1 ；r20 = C ／ C₋₂₀ − 1
above60= C > MA60
slope60= MA60 − MA60₋₅ （描述欄位；v1 的「暫不進場」用它，v2 不當濾網）
liq20  = 近 20 日平均成交金額（R3）
R2 濾網（大盤）：benchmark C < MA60 → 當日不開新倉（r2_off=True）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    hi, lo = df["high"].fillna(df["close"]), df["low"].fillna(df["close"])
    return pd.concat([hi - lo, (hi - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """輸入統一欄位價格表（依 date 升序），回傳加上特徵欄的新表。"""
    out = df.copy()
    c = out["close"]
    out["ma20"] = c.rolling(C.MA_SHORT).mean()
    out["ma60"] = c.rolling(C.MA_LONG).mean()
    out["atr14"] = true_range(out).rolling(C.ATR_N).mean()
    out["ext"] = (c - out["ma20"]) / out["atr14"].replace(0, np.nan)
    out["r5"] = c / c.shift(C.R5_N) - 1
    out["r20"] = c / c.shift(C.R20_N) - 1
    out["above60"] = c > out["ma60"]
    out["slope60"] = out["ma60"] - out["ma60"].shift(5)
    out["liq20"] = out["amount"].rolling(C.LIQ_N).mean()
    return out


def r2_filter(bench: pd.DataFrame) -> pd.Series:
    """大盤濾網：回傳以 date 為索引的布林序列，True＝當日不開新倉。"""
    ma = bench["close"].rolling(C.MA_LONG).mean()
    off = (bench["close"] < ma)
    return pd.Series(off.values, index=bench["date"].values, name="r2_off")


def liq_pass(row_or_series, market: str):
    return row_or_series >= C.LIQ_MIN[market]


def rank_candidates(snapshot: pd.DataFrame, market: str, score: str = "ext", top_n: int = C.TOP_N) -> pd.DataFrame:
    """snapshot：同一天、多檔的一列一檔特徵表（含 code, ext, r20, above60, liq20）。
    R1：只排 above60 且 R3 通過者，依 score 由高到低取前 top_n；回傳含 rank 欄的子表。
    tie-break 用 code，排名才穩定。"""
    s = snapshot[(snapshot["above60"] == True) & liq_pass(snapshot["liq20"], market) & snapshot[score].notna()]  # noqa: E712
    s = s.sort_values([score, "code"], ascending=[False, True]).head(top_n).copy()
    s["rank"] = range(1, len(s) + 1)
    return s
