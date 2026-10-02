# -*- coding: utf-8 -*-
"""資料層：FinMind 還原價（台股 TaiwanStockPriceAdj／美股 USStockPrice）＋大盤基準，逐檔 parquet 快取。

統一欄位：date(str YYYY-MM-DD), open, high, low, close, volume, amount
- 台股：open/max/min/close 已是還原價；amount＝Trading_money（元）
- 美股：以 Adj_Close／Close 的比例把 OHLC 調成還原價；amount＝Close×Volume（美元，近似）
token：環境變數 FINMIND_TOKEN 或 repo 根目錄 .env；錯誤訊息一律經 mask_secret（token 不進 log）。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from . import config as C

API_SLEEP = 0.3
_TOKEN: Optional[str] = None


def load_token() -> str:
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    tok = os.environ.get("FINMIND_TOKEN", "").strip()
    if not tok:
        env = C.REPO_DIR / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("FINMIND_TOKEN="):
                    tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        raise RuntimeError("找不到 FINMIND_TOKEN（環境變數或 .env）")
    _TOKEN = tok
    return tok


def mask_secret(msg) -> str:
    s = str(msg)
    tok = (_TOKEN or os.environ.get("FINMIND_TOKEN") or "").strip()
    if len(tok) >= 8:
        s = s.replace(tok, "***")
    return re.sub(r"(token=)[^&\s]+", r"\1***", s)


def fm_get(dataset: str, data_id: str, start: str, end: str | None = None,
           retries: int = 3, backoff: float = 5.0, session=None) -> Optional[pd.DataFrame]:
    """回 DataFrame（可為空）或 None（失敗）。"""
    import requests
    s = session or requests
    params = {"dataset": dataset, "data_id": data_id, "start_date": start, "token": load_token()}
    if end:
        params["end_date"] = end
    last = None
    for att in range(retries):
        try:
            r = s.get(C.FM_API, params=params, timeout=60)
            j = r.json()
            if j.get("status") == 200:
                time.sleep(API_SLEEP)
                return pd.DataFrame(j.get("data", []))
            last = f"status={j.get('status')} msg={j.get('msg')}"
        except Exception as e:  # noqa: BLE001
            last = mask_secret(e)
        time.sleep(backoff * (2 ** att))
    print(f"[warn] fm_get {dataset}/{data_id} 失敗：{mask_secret(last)}")
    return None


def normalize(raw: pd.DataFrame, market: str) -> pd.DataFrame:
    """把 FinMind 原始欄位轉成統一欄位；空輸入回空表。"""
    cols = ["date", "open", "high", "low", "close", "volume", "amount"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    df = raw.copy()
    if market == "TW":
        df = df.rename(columns={"max": "high", "min": "low",
                                "Trading_Volume": "volume", "Trading_money": "amount"})
    else:
        adj = pd.to_numeric(df["Adj_Close"], errors="coerce")
        close = pd.to_numeric(df["Close"], errors="coerce")
        f = (adj / close).where(close > 0, 1.0).fillna(1.0)
        out = pd.DataFrame({"date": df["date"]})
        out["open"] = pd.to_numeric(df["Open"], errors="coerce") * f
        out["high"] = pd.to_numeric(df["High"], errors="coerce") * f
        out["low"] = pd.to_numeric(df["Low"], errors="coerce") * f
        out["close"] = adj
        out["volume"] = pd.to_numeric(df["Volume"], errors="coerce")
        out["amount"] = close * out["volume"]
        df = out
    df = df[cols].copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = df["date"].astype(str).str[:10]
    df = df.dropna(subset=["close"]).drop_duplicates("date").sort_values("date")
    return df.reset_index(drop=True)


def cache_path(market: str, code: str) -> Path:
    return C.PRICE_CACHE_DIR / market / f"{code.replace('^', '_')}.parquet"


def load_prices(market: str, code: str, start: str = C.SAMPLE_START, dataset: str | None = None,
                refresh: bool = True, fetch: Callable | None = None) -> pd.DataFrame:
    """讀快取並增量補到最新；fetch 可注入（測試）。refresh=False 只讀快取。"""
    p = cache_path(market, code)
    cached = pd.read_parquet(p) if p.exists() else pd.DataFrame()
    if not refresh:
        return cached
    fetch = fetch or fm_get
    ds = dataset or C.FM_DATASET[market]
    # 從快取末日重抓（含末日，覆寫以吸收還原價調整的最後一列）
    since = cached["date"].max() if not cached.empty else start
    raw = fetch(ds, code, since)
    if raw is None:
        return cached
    new = normalize(raw, market)
    if cached.empty:
        df = new
    else:
        df = pd.concat([cached[cached["date"] < since], new]).drop_duplicates("date", keep="last")
        df = df.sort_values("date").reset_index(drop=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return df


def load_benchmark(market: str, uni: dict, **kw) -> pd.DataFrame:
    b = uni["benchmarks"][market]
    return load_prices(market, b["data_id"], dataset=b["dataset"], **kw)


def load_all(uni: dict, markets=("TW", "US"), **kw) -> dict[tuple[str, str], pd.DataFrame]:
    out = {}
    for m in markets:
        for code in C.universe_codes(uni, m):
            out[(m, code)] = load_prices(m, code, **kw)
    return out
