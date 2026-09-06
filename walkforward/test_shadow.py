#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shadow_daily.simulate_shadow 離線單元測試(免 token 免網路)。
執行: python3 walkforward/test_shadow.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shadow_daily import simulate_shadow, COST  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = all(abs(a - b) < 1e-9 if isinstance(a, float) else a == b
             for a, b in zip(got, want))
    print(("  ✓ " if ok else "  ✗ ") + name +
          ("" if ok else f"  got={got} want={want}"))
    if not ok:
        FAIL.append(name)


def mk(*minute_prices):
    """minute_prices: ('HH:MM', [p1, p2, ...]) -> (times, prices) tick 流。"""
    times, prices = [], []
    for m, ps in minute_prices:
        for i, p in enumerate(ps):
            times.append(f"{m}:{i:02d}")
            prices.append(float(p))
    return times, prices


E = 10000.0        # 進場價; R = 75, 0.5R = 37.5, 保本價(多)=10002
R = E * 0.0075

# T1 多單基礎停損: 觸 9925 -> -R-COST, 出場 9925
t, p = mk(("08:45", [E, 9990]), ("08:46", [9925, 9980]))
for v in "AB":
    check(f"T1 基礎停損({v})", simulate_shadow(t, p, 0, 1, v),
          (-R - COST, "stop", E - R))

# T2 武裝後次分鐘觸保本: 08:46 漲到 10080(武裝), 08:47 跌破 10002 -> be_stop, pnl 0
t, p = mk(("08:45", [E, 10010]), ("08:46", [10080]), ("08:47", [10050, 10001]))
for v in "AB":
    check(f"T2 保本出場({v})", simulate_shadow(t, p, 0, 1, v),
          (0.0, "be_stop", 10002.0))

# T3 同分鐘武裝+回落不生效: 08:46 內衝 10080 又回 9990(高於基礎停損), 08:47 收復
t, p = mk(("08:45", [E]), ("08:46", [10080, 9990]), ("08:47", [10030]))
check("T3 同分鐘不生效->close", simulate_shadow(t, p, 0, 1, "A"),
      ((10030 - E) - COST, "close", 10030.0))

# T4 未武裝小幅震盪 -> 收盤平
t, p = mk(("08:45", [E, 10010]), ("08:46", [9990]), ("13:44", [10020]))
check("T4 收盤平", simulate_shadow(t, p, 0, 1, "A"),
      (20.0 - COST, "close", 10020.0))

# T5 空單保本: 跌到 9925 武裝, 次分鐘彈回 >=9998 -> be_stop at 9998, pnl 0
t, p = mk(("08:45", [E, 9970]), ("08:46", [9925]), ("08:47", [9960, 9999]))
check("T5 空單保本", simulate_shadow(t, p, 0, -1, "A"), (0.0, "be_stop", 9998.0))

# T6 時間停損: 60 分鐘皆小幅負值(MFE=10 < 37.5), 09:45 分鐘末淨損益<0
#    -> 09:46 首筆 9985 出場(B); A 同資料走到收盤
mins = [("08:45", [E, 10010])]
for k in range(46, 60):
    mins.append((f"08:{k}", [9995]))
for k in range(0, 46):
    mins.append((f"09:{k:02d}", [9990]))
mins.append(("09:46", [9985]))
mins.append(("13:44", [10030]))
t, p = mk(*mins)
check("T6 時間停損(B)", simulate_shadow(t, p, 0, 1, "B"),
      ((9985 - E) - COST, "time_stop", 9985.0))
check("T6 對照: A 不時間停損", simulate_shadow(t, p, 0, 1, "A"),
      (30.0 - COST, "close", 10030.0))

# T7 MFE>=0.5R 免時間停損: 早段衝 +40(>37.5) 後轉負, B 仍走到收盤
mins = [("08:45", [E, 10040])]
for k in range(46, 60):
    mins.append((f"08:{k}", [9995]))
for k in range(0, 50):
    mins.append((f"09:{k:02d}", [9990]))
mins.append(("13:44", [9992]))
t, p = mk(*mins)
check("T7 MFE達標免時停(B)", simulate_shadow(t, p, 0, 1, "B"),
      ((9992 - E) - COST, "close", 9992.0))

# T8 B 仍吃基礎停損(時停之前先觸價)
t, p = mk(("08:45", [E]), ("08:46", [9920]))
check("T8 B基礎停損", simulate_shadow(t, p, 0, 1, "B"), (-R - COST, "stop", E - R))

# T9 10:00 進場(空1000 情境): entry_i 指向 10:00 首筆, 之前的價不影響
t, p = mk(("08:45", [9800, 9900]), ("10:00", [E, 9970]), ("10:01", [9925]),
          ("10:02", [9960, 9999]))
check("T9 延後進場+空單保本", simulate_shadow(t, p, 2, -1, "A"),
      (0.0, "be_stop", 9998.0))

print()
if FAIL:
    print(f"失敗 {len(FAIL)} 項: {FAIL}"); sys.exit(1)
print("全部通過")
