#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""國定假日行事曆接入（2026-09-29）的離線測試（免 token 免網路）。
執行: python3 walkforward/test_holidays.py
假行事曆由測試注入（fetch 參數）, 不依賴網路與今天日期。"""
import csv
import datetime as dt
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import twse_holidays as th  # noqa: E402
import walkforward_daily as wd  # noqa: E402
import shadow_daily as sd  # noqa: E402

TPE = ZoneInfo("Asia/Taipei")
FAIL = []


def check(name, ok, detail=""):
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        FAIL.append(name)


DOC = {"schema": 1, "source": "x", "fetched_at": "2026-09-29T08:00:00+08:00",
       "years": [2026], "closed": ["2026-01-01", "2026-09-25", "2026-09-28", "2026-10-10"],
       "names": {"2026-09-25": "中秋節", "2026-09-28": "教師節"}, "raw_n": 27}


def fetch_doc(doc):
    return lambda url, timeout: json.dumps(doc, ensure_ascii=False).encode("utf-8")


def fetch_404(url, timeout):
    raise RuntimeError("HTTP 404")


def fetch_bad(url, timeout):
    return b"<html>not json"


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


D = dt.date
# ---- skip_reason / parse 單元 ----
r, out = quiet(th.skip_reason, D(2026, 9, 25), fetch_doc(DOC))
check("09-25 週五假日→跳過", r == "2026-09-25 國定假日（中秋節），跳過", r)
r, _ = quiet(th.skip_reason, D(2026, 9, 28), fetch_doc(DOC))
check("09-28 週一假日→跳過", r == "2026-09-28 國定假日（教師節），跳過", r)
r, _ = quiet(th.skip_reason, D(2026, 9, 29), fetch_doc(DOC))
check("09-29 平日→照常", r is None, r)
r, _ = quiet(th.skip_reason, D(2026, 9, 26), fetch_404)
check("09-26 週六→週末跳過(不需行事曆)", r == "2026-09-26 週末, 跳過", r)
for nm, f in [("404", fetch_404), ("壞檔", fetch_bad)]:
    r, out = quiet(th.skip_reason, D(2026, 9, 25), f)
    check(f"行事曆{nm}→fail-open(假日照常走)", r is None and "::warning::" in out, (r, out))
r, out = quiet(th.skip_reason, D(2027, 1, 1), fetch_doc(DOC))
check("年度未涵蓋→fail-open 只排週末", r is None and "未涵蓋 2027" in out, (r, out))
check("schema true 拒收", th.parse(dict(DOC, schema=True)) is None)
check("schema '1' 拒收", th.parse(dict(DOC, schema="1")) is None)
check("years 含 bool 拒收", th.parse(dict(DOC, years=[True])) is None)
check("closed 格式錯拒收", th.parse(dict(DOC, closed=["2026/09/25"])) is None)
check("合法檔可解析", th.parse(DOC) is not None and th.parse(DOC).is_holiday("2026-09-25"))
r, out = quiet(th.skip_reason, D(2026, 9, 25), fetch_doc(dict(DOC, schema=True)))
check("schema true→fail-open(假日照常走)", r is None and "形狀不合" in out, (r, out))


# ---- main() 整合: 假日不打 API、不寫帳冊; 平日照常往下走(打到 API 為止) ----
class ApiCalled(Exception):
    pass


def boom(params):
    raise ApiCalled(params.get("dataset"))


def run_main(mod, now, fetch):
    """把帳冊路徑導到暫存目錄、TOKEN 設假值、api_get 換成會拋例外的替身。
    回傳 (是否打到 API, 暫存目錄內檔案列表, stdout)。"""
    tmp = Path(tempfile.mkdtemp())
    seed = ["2026-09-24", "2026-09-23", "-0.01226", "跌-2~-1%", "空0845", "08:45",
            "47850.0", "48208.9", "stop", "-360.9", "-1012.8"]
    saved = {"TOKEN": mod.TOKEN, "api_get": mod.api_get}
    if mod is wd:
        saved["LEDGER"] = wd.LEDGER
        wd.LEDGER = tmp / "ledger.csv"
        paths = [wd.LEDGER]
    else:
        saved["LEDGERS"] = sd.LEDGERS
        sd.LEDGERS = {"A": tmp / "a.csv", "B": tmp / "b.csv"}
        paths = list(sd.LEDGERS.values())
    for p in paths:
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(mod.COLS)
            w.writerow(seed)
    before = [p.read_bytes() for p in paths]
    mod.TOKEN, mod.api_get = "dummy", boom
    called = False
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            mod.main(now=now, holiday_fetch=fetch)
    except ApiCalled:
        called = True
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
    unchanged = [p.read_bytes() for p in paths] == before
    return called, unchanged, buf.getvalue()


for mod, nm in [(wd, "正式"), (sd, "影子")]:
    # 台北 09-25 21:07 主班 / 09-26 01:30 跨午夜延遲 → target 皆 09-25
    for now in [dt.datetime(2026, 9, 25, 21, 7, tzinfo=TPE),
                dt.datetime(2026, 9, 26, 1, 30, tzinfo=TPE)]:
        called, unchanged, out = run_main(mod, now, fetch_doc(DOC))
        check(f"{nm} main {now:%m-%d %H:%M} → 09-25 跳過、不打 API、帳冊不變",
              not called and unchanged and "國定假日（中秋節）" in out, (called, unchanged, out))
    called, unchanged, out = run_main(mod, dt.datetime(2026, 9, 28, 21, 7, tzinfo=TPE),
                                      fetch_doc(DOC))
    check(f"{nm} main 09-28 週一假日跳過", not called and unchanged, (called, out))
    called, _, out = run_main(mod, dt.datetime(2026, 9, 29, 21, 7, tzinfo=TPE), fetch_doc(DOC))
    check(f"{nm} main 09-29 平日照常往下走(打到 API)", called, out)
    called, _, out = run_main(mod, dt.datetime(2026, 9, 25, 21, 7, tzinfo=TPE), fetch_404)
    check(f"{nm} main 行事曆 404 → fail-open 照舊往下走", called and "::warning::" in out, out)
    called, unchanged, out = run_main(mod, dt.datetime(2026, 9, 26, 21, 7, tzinfo=TPE), fetch_404)
    check(f"{nm} main 週六 → 週末跳過", not called and unchanged and "週末" in out, out)

print()
if FAIL:
    print(f"失敗 {len(FAIL)} 項: {FAIL}"); sys.exit(1)
print("全部通過")
