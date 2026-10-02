# -*- coding: utf-8 -*-
"""IBKR Flex Web Service 唯讀對帳（Phase 0 第 2 項）。

流程（IBKR 官方 Flex Web Service v3）：
  1. SendRequest?t=<token>&q=<queryId>&v=3  → XML，Status=Success 時帶 ReferenceCode
  2. GetStatement?q=<ReferenceCode>&t=<token>&v=3 → 報表本體（建議 Flex Query 設為 CSV）
     報表尚未產好時回 ErrorCode 1019（"Statement generation in progress"），退避重試。
限制：token 可綁 IP、每分鐘約 10 次請求；報表只存 AISC_PRIVATE_DIR（預設 ~/.aisc）/ibkr/，不進 repo。
環境變數：IBKR_FLEX_TOKEN、IBKR_FLEX_QUERY_ID（持倉／成交查詢的 Query ID，於 Client Portal 建立）。
token 絕不印出；任何錯誤訊息都先遮罩。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config as C

BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
IN_PROGRESS_CODES = {"1019", "1021"}


def _mask(s: str) -> str:
    s = str(s)
    tok = os.environ.get("IBKR_FLEX_TOKEN", "")
    if len(tok) >= 8:
        s = s.replace(tok, "***")
    return re.sub(r"([?&]t=)[^&\s]+", r"\1***", s)


def _get(url: str, opener=urllib.request.urlopen) -> str:
    with opener(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def send_request(token: str, query_id: str, opener=urllib.request.urlopen) -> str:
    url = f"{BASE}/SendRequest?" + urllib.parse.urlencode({"t": token, "q": query_id, "v": "3"})
    root = ET.fromstring(_get(url, opener))
    status = (root.findtext("Status") or "").strip()
    if status != "Success":
        raise RuntimeError(_mask(f"SendRequest 失敗：{root.findtext('ErrorCode')} {root.findtext('ErrorMessage')}"))
    return (root.findtext("ReferenceCode") or "").strip()


def get_statement(token: str, ref: str, opener=urllib.request.urlopen, tries: int = 8, wait: float = 8.0) -> str:
    url = f"{BASE}/GetStatement?" + urllib.parse.urlencode({"q": ref, "t": token, "v": "3"})
    for _ in range(tries):
        body = _get(url, opener)
        if body.lstrip().startswith("<FlexStatementResponse"):
            root = ET.fromstring(body)
            code = (root.findtext("ErrorCode") or "").strip()
            if code in IN_PROGRESS_CODES:
                time.sleep(wait)
                continue
            raise RuntimeError(_mask(f"GetStatement 失敗：{code} {root.findtext('ErrorMessage')}"))
        return body
    raise TimeoutError("GetStatement 等待報表產生逾時")


def fetch_and_store(out_dir: Path | None = None, opener=urllib.request.urlopen) -> Path:
    token = os.environ.get("IBKR_FLEX_TOKEN", "").strip()
    qid = os.environ.get("IBKR_FLEX_QUERY_ID", "").strip()
    if not token or not qid:
        raise RuntimeError("需要 IBKR_FLEX_TOKEN 與 IBKR_FLEX_QUERY_ID")
    out_dir = out_dir or (C.PRIVATE_DIR / "ibkr")
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = send_request(token, qid, opener)
    body = get_statement(token, ref, opener)
    p = out_dir / f"flex_{qid}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    p.write_text(body, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IBKR Flex 唯讀報表抓取（不送單）")
    ap.add_argument("--out", help="輸出目錄（預設 $AISC_PRIVATE_DIR/ibkr，不在 repo 內）")
    a = ap.parse_args(argv)
    try:
        p = fetch_and_store(Path(a.out) if a.out else None)
    except Exception as e:  # noqa: BLE001
        print(f"[error] {_mask(e)}")
        return 1
    print(f"已存 {p}（{p.stat().st_size} bytes）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
