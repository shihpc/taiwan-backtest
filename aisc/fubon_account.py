# -*- coding: utf-8 -*-
"""富邦證券 fubon_neo 唯讀帳務骨架（Phase 0 第 3 項；規格 §6 已選定富邦）。

⚠ 本檔只做「登入 → 查庫存／未實現損益 → 存到私人目錄」，**沒有任何下單呼叫**，
   fubon_neo 的 place_order 等方法刻意不 import、不包裝。
⚠ fubon_neo SDK 要從富邦官網下載 wheel 自行安裝，本沙箱沒有；以下方法名依 2026 年公開文件撰寫，
   **未在真 SDK 上實跑**，第一次在本機跑時請對照 SDK 的 README 校正（標 TODO 處）。
環境變數（不進 repo）：FUBON_ID（身分證字號）、FUBON_PWD、FUBON_CERT_PATH（.pfx 憑證路徑）、FUBON_CERT_PWD。
輸出：AISC_PRIVATE_DIR/fubon/inventory_<ts>.json，權限 0600。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import config as C

REQUIRED_ENV = ("FUBON_ID", "FUBON_PWD", "FUBON_CERT_PATH", "FUBON_CERT_PWD")


def _env() -> dict:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError("缺環境變數：" + ", ".join(missing))
    return {k: os.environ[k] for k in REQUIRED_ENV}


def _to_plain(obj):
    """SDK 回傳物件 → 可 JSON 化的 dict／list（盡量不假設型別）。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    d = getattr(obj, "__dict__", None)
    if d:
        return {k: _to_plain(v) for k, v in d.items() if not k.startswith("_")}
    return str(obj)


def fetch_inventory(sdk=None) -> dict:
    env = _env()
    if sdk is None:
        try:
            from fubon_neo.sdk import FubonSDK  # type: ignore
        except ImportError as e:
            raise RuntimeError("未安裝 fubon_neo（請自富邦官網下載 wheel 安裝）") from e
        sdk = FubonSDK()
    # TODO(實機校正)：login 參數順序與回傳形狀依 SDK README 為準
    res = sdk.login(env["FUBON_ID"], env["FUBON_PWD"], env["FUBON_CERT_PATH"], env["FUBON_CERT_PWD"])
    accounts = getattr(res, "data", res)
    if not accounts:
        raise RuntimeError("登入成功但無帳戶")
    out = {"fetched_at": dt.datetime.now().isoformat(timespec="seconds"), "accounts": []}
    for acc in accounts:
        # TODO(實機校正)：唯讀帳務方法名（inventories／unrealized_gains_and_loses）依 SDK 為準
        inv = sdk.accounting.inventories(acc)
        pnl = sdk.accounting.unrealized_gains_and_loses(acc)
        out["accounts"].append({
            "account": _to_plain(getattr(acc, "account", acc)),
            "inventories": _to_plain(getattr(inv, "data", inv)),
            "unrealized": _to_plain(getattr(pnl, "data", pnl)),
        })
    try:
        sdk.logout()
    except Exception:  # noqa: BLE001
        pass
    return out


def store(payload: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (C.PRIVATE_DIR / "fubon")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"inventory_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="富邦 fubon_neo 唯讀庫存查詢（不送單）")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        p = store(fetch_inventory(), Path(a.out) if a.out else None)
    except Exception as e:  # noqa: BLE001
        print(f"[error] {type(e).__name__}: {e}")
        return 1
    print(f"已存 {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
