#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""家族共用國定假日行事曆的消費端（2026-09-29，walkforward 兩支腳本共用）。

規格正本: taiwan-flow-live-v2 docs/holiday-calendar.md（§1 資料契約、§2 消費端共同規則）。
參考實作: taiwan-flows src/twse_holidays.py（parse 規則逐條相同）。
資料唯一來源＝taiwan-flow-live-v2 的 data/twse_holidays.json（raw main）。

fail-open（§2）: 讀不到（404／逾時／網路例外）、壞檔（非 JSON／形狀不合）、或目標年度不在
years 裡，一律退回「只排週末」的舊行為——絕不拋例外、絕不因行事曆掛掉而擋掉真交易日。
抓取可注入（fetch 參數），離線測試不打網路。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from typing import Callable

HOLIDAYS_URL = ("https://raw.githubusercontent.com/shihpc/taiwan-flow-live-v2/"
                "main/data/twse_holidays.json")
FETCH_TIMEOUT_SEC = 10
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Fetch = Callable[[str, float], "str | bytes"]


@dataclass(frozen=True)
class TwseHolidays:
    years: frozenset
    closed: frozenset
    names: dict = field(default_factory=dict)

    def covers(self, day: str) -> bool:
        try:
            return int(day[:4]) in self.years
        except (TypeError, ValueError):
            return False

    def is_holiday(self, day: str) -> bool:
        """年度未涵蓋一律 False（＝只排週末, fail-open）。"""
        return self.covers(day) and day in self.closed

    def name(self, day: str) -> str:
        return self.names.get(day, "") if self.is_holiday(day) else ""


def _default_fetch(url: str, timeout: float) -> bytes:
    import requests
    r = requests.get(url, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.content


def parse(doc: object) -> TwseHolidays | None:
    """驗 §1 契約形狀; 任一處不合回 None。schema 必須恰為整數 1（排除 bool: True == 1）。"""
    if not isinstance(doc, dict) or doc.get("schema") != 1 \
            or isinstance(doc.get("schema"), bool):
        return None
    years, closed, names = doc.get("years"), doc.get("closed"), doc.get("names") or {}
    if not isinstance(years, list) or not years or \
            not all(isinstance(y, int) and not isinstance(y, bool) for y in years):
        return None
    if not isinstance(closed, list) or \
            not all(isinstance(d, str) and _DATE_RE.match(d) for d in closed):
        return None
    if not isinstance(names, dict):
        names = {}
    return TwseHolidays(frozenset(years), frozenset(closed),
                        {str(k): str(v) for k, v in names.items()})


def load(fetch: Fetch | None = None, url: str = HOLIDAYS_URL,
         timeout: float = FETCH_TIMEOUT_SEC) -> TwseHolidays | None:
    """抓並解析; 失敗（含任何例外）回 None 並印一行警示, 不拋。"""
    try:
        raw = (fetch or _default_fetch)(url, timeout)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        cal = parse(json.loads(raw))
    except Exception as e:  # noqa: BLE001 — fail-open
        print(f"::warning::國定假日行事曆讀不到（{type(e).__name__}: {e}），退回只排週末")
        return None
    if cal is None:
        print("::warning::國定假日行事曆形狀不合契約（schema／years／closed），退回只排週末")
    return cal


def skip_reason(target: dt.date, fetch: Fetch | None = None) -> str | None:
    """walkforward 兩支腳本共用的「非交易日」判定。回傳要印的跳過訊息; None＝照常往下走。
    週末不打網路; 平日才讀行事曆（讀不到／年度未涵蓋 → 印警示後回 None＝只排週末）。"""
    if target.weekday() >= 5:
        return f"{target} 週末, 跳過"
    tstr = str(target)
    cal = load(fetch)
    if cal is None:
        return None
    if not cal.covers(tstr):
        print(f"::warning::國定假日行事曆未涵蓋 {target.year} 年（years={sorted(cal.years)}），"
              "退回只排週末")
        return None
    if cal.is_holiday(tstr):
        return f"{tstr} 國定假日（{cal.name(tstr) or '休市'}），跳過"
    return None
