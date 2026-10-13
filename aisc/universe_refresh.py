# -*- coding: utf-8 -*-
"""候選池浮動：台股每月 11 號起第一班，以 postmkt screen.json 整池替換（使用者 2026-10-13 裁定）。

規則（回測前寫死，改＝新裁定）：
- 到期：台北今日 ≥ 當月 REFRESH_DAY（11）號，且上次台股換池日 < 當月 11 號。cron 只跑週一~五，
  11 號逢週末就落到之後第一班。
- 來源：postmkt `data/screen/screen.json`（明年預估 EPS ≥ 20 初篩），只取 code／name，依代號排序後整池替換。
- 守門（任一不過＝不換、保留舊名單、回非 0 碼，下一班重試）：見 `validate_screen`。
- 美股 24 檔沒有對應來源，維持 2026-10-02 凍結；benchmarks 不動。
- v2 回測讀 `universe_v1.json`（凍結 117 檔），不受本模組影響。
- 浮動池沒有歷史可回測（screen.json 沒有 2021 起逐月的時點資料），只能從生效日起前推。

用法：
  python3 -m aisc.universe_refresh              # 到期才換池，寫 aisc/universe.json
  python3 -m aisc.universe_refresh --dry-run    # 只印結果不寫檔
  python3 -m aisc.universe_refresh --force      # 不看到期（手動補換）；守門照跑
退出碼：0＝未到期或已換池；5＝到期但來源未通過守門（不換）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config as C

TPE = ZoneInfo("Asia/Taipei")
CODE_RE = re.compile(r"\d{4}[0-9A-Z]{0,2}")   # 一律 fullmatch（match＋$ 會放行尾端 \n）


class ScreenRejected(Exception):
    pass


def taipei_today() -> dt.date:
    return dt.datetime.now(TPE).date()


def last_refresh(uni: dict) -> dt.date:
    return dt.date.fromisoformat(uni.get("tw_refreshed_at") or uni["frozen_at"])


def refresh_due(uni: dict, today: dt.date) -> bool:
    if today.day < C.REFRESH_DAY:
        return False
    return last_refresh(uni) < today.replace(day=C.REFRESH_DAY)


def fetch_screen(url: str = C.SCREEN_URL, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "aisc-universe-refresh"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # 固定的 https raw URL
        return json.loads(r.read().decode("utf-8"))


def _gen_date(s) -> dt.date | None:
    try:
        t = dt.datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return (t.astimezone(TPE) if t.tzinfo else t).date()


def validate_screen(screen, today: dt.date, n_current: int) -> list[dict]:
    """通過回傳依代號排序的 [{code,name}]；不通過丟 ScreenRejected（附原因）。"""
    if not isinstance(screen, dict):
        raise ScreenRejected("screen.json 不是物件")
    rows = screen.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ScreenRejected("rows 缺或為空")
    if screen.get("min_feps") != C.SCREEN_MIN_FEPS:
        raise ScreenRejected(f"min_feps={screen.get('min_feps')!r}，須為 {C.SCREEN_MIN_FEPS}")
    if screen.get("n") != len(rows):
        raise ScreenRejected(f"n={screen.get('n')!r} 與 rows 列數 {len(rows)} 不符")
    gen = _gen_date(screen.get("generated_at"))
    if gen is None:
        raise ScreenRejected(f"generated_at 無法解析：{screen.get('generated_at')!r}")
    floor = today.replace(day=C.SCREEN_MIN_GEN_DAY)
    if floor > today:   # --force 在 10 號前：以上個月 10 號為下限
        floor = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=C.SCREEN_MIN_GEN_DAY)
    if not (floor <= gen <= today):
        raise ScreenRejected(f"generated_at 台北日 {gen} 不在 {floor}～{today}（須為當月月營收公布後的版本）")
    out, seen = [], set()
    for r in rows:
        code, name = (r.get("code"), r.get("name")) if isinstance(r, dict) else (None, None)
        if not (isinstance(code, str) and CODE_RE.fullmatch(code) and isinstance(name, str) and name.strip()):
            raise ScreenRejected(f"列格式不合：{str(r)[:80]}")
        if code in seen:
            raise ScreenRejected(f"代號重複：{code}")
        seen.add(code)
        out.append({"code": code, "name": name.strip()})
    if len(out) < n_current * C.REFRESH_MIN_FRAC:
        raise ScreenRejected(f"新名單 {len(out)} 檔 < 現有 {n_current} 檔 × {C.REFRESH_MIN_FRAC}，疑上游殘缺")
    return sorted(out, key=lambda x: x["code"])


def apply_refresh(uni: dict, tw: list[dict], screen: dict, today: dt.date) -> dict:
    old = {x["code"] for x in uni["TW"]}
    new = {x["code"] for x in tw}
    out = dict(uni)
    out["TW"] = tw
    out["tw_refreshed_at"] = today.isoformat()
    out["version"] = f"float-{today:%Y-%m}"
    out["changes"] = list(uni.get("changes", [])) + [{
        "date": today.isoformat(),
        "reason": f"每月 {C.REFRESH_DAY} 號浮動換池（台股；美股維持凍結）",
        "source": {"file": "postmkt data/screen/screen.json", "date": screen.get("date"),
                   "generated_at": screen.get("generated_at"), "min_feps": screen.get("min_feps"), "n": len(tw)},
        "added": sorted(new - old),
        "removed": sorted(old - new),
    }]
    return out


def run(path: Path = C.UNIVERSE_PATH, today: dt.date | None = None, fetch: Callable[[], dict] | None = None,
        force: bool = False, dry_run: bool = False) -> tuple[int, str]:
    today = today or taipei_today()
    uni = C.load_universe(path)
    if not force and not refresh_due(uni, today):
        return 0, f"未到期（今日 {today}，上次台股換池 {last_refresh(uni)}）"
    try:
        screen = (fetch or fetch_screen)()
        tw = validate_screen(screen, today, len(uni["TW"]))
    except ScreenRejected as e:
        return 5, f"::warning::候選池到期但不換池（保留舊名單，下一班重試）：{e}"
    except Exception as e:  # noqa: BLE001  抓取失敗同樣不換、不擋每日表
        return 5, f"::warning::候選池到期但抓 screen.json 失敗（保留舊名單，下一班重試）：{type(e).__name__}: {e}"
    new_uni = apply_refresh(uni, tw, screen, today)
    ch = new_uni["changes"][-1]
    msg = (f"候選池換池 {today}：台股 {len(uni['TW'])}→{len(tw)} 檔，"
           f"新增 {len(ch['added'])}{ch['added'][:20]}、移除 {len(ch['removed'])}{ch['removed'][:20]}"
           f"（screen {screen.get('date')}／{screen.get('generated_at')}）")
    if not dry_run:
        Path(path).write_text(json.dumps(new_uni, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0, msg + ("（dry-run，未寫檔）" if dry_run else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="不看到期，守門照跑")
    a = ap.parse_args(argv)
    rc, msg = run(force=a.force, dry_run=a.dry_run)
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
