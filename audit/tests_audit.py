#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稽核引擎回歸測試 — 離線、免資料。python3 audit/tests_audit.py 或 pytest 皆可。"""
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from engine import max_drawdown, signal_bucket, simulate_day  # noqa: E402

FAIL = []

def eq(name, got, want, tol=1e-9):
    ok = (got is want) if want is None else (
        got == want if isinstance(want, str) else abs(got - want) <= tol)
    if not ok:
        FAIL.append(f"{name}: got {got!r} want {want!r}")
    print(("  ✓ " if ok else "  ✗ ") + f"{name}: {got!r}")

# ---- P0-1 MDD 含起始權益 ----
eq("MDD [-100,20]", max_drawdown([-100, 20]), -100)
eq("MDD [100,-150]", max_drawdown([100, -150]), -150)
eq("MDD [-100,-50]", max_drawdown([-100, -50]), -150)
eq("MDD [] (語意: 無交易=0)", max_drawdown([]), 0.0)
eq("MDD [50,20,-30] (不破起始)", max_drawdown([50, 20, -30]), -30)

# ---- P0-2 跳空穿越停損 ----
# 多單: 進場 100(第0根), 第1根 open=98 high=98 low=97; SL0.75% 觸發價 99.25
op, hi, lo = np.array([100.0, 98]), np.array([100.0, 98]), np.array([99.5, 97])
pnl, how, ex = simulate_day(op, hi, lo, 97.5, 0, 100.0, 1, 0.0075,
                            cost=0, slip=0, fill_model="gap")
eq("多單跳空 pnl", pnl, -2.0)
eq("多單跳空 how", how, "stop_gap")
# 空單對稱: 進場 100, 第1根 open=102 high=103 low=102; 觸發 100.75
op, hi, lo = np.array([100.0, 102]), np.array([100.5, 103]), np.array([100.0, 102])
pnl, how, ex = simulate_day(op, hi, lo, 102.5, 0, 100.0, -1, 0.0075,
                            cost=0, slip=0, fill_model="gap")
eq("空單跳空 pnl", pnl, -2.0)
eq("空單跳空 how", how, "stop_gap")
# 舊 ideal 模型同情境: 幻覺式 -0.75
pnl, how, ex = simulate_day(op, hi, lo, 102.5, 0, 100.0, -1, 0.0075,
                            cost=0, slip=0, fill_model="ideal")
eq("ideal 同情境 pnl(舊模型幻覺)", pnl, -0.75)
# 盤中正常觸價(無跳空): 多單 100, 第1根 open=100 low=99 -> 取整停損 99.25->99, 滑價1 -> 98
op, hi, lo = np.array([100.0, 100]), np.array([100.0, 100]), np.array([99.8, 99])
pnl, how, ex = simulate_day(op, hi, lo, 99.5, 0, 100.0, 1, 0.0075,
                            cost=0, slip=1.0, fill_model="gap")
eq("盤中觸價 tick取整+滑價 exit", ex, 98.0)
eq("盤中觸價 pnl", pnl, -2.0)
# 未觸損 -> 收盤平
op, hi, lo = np.array([100.0, 101]), np.array([100.5, 101.5]), np.array([99.9, 100.5])
pnl, how, ex = simulate_day(op, hi, lo, 101.0, 0, 100.0, 1, 0.0075,
                            cost=2.0, slip=0, fill_model="gap")
eq("未觸損收盤平 pnl", pnl, -1.0)
eq("未觸損 how", how, "close")
# 掃描自 entry_i 起: entry_i=1 時第0根的崩跌不得觸發
op, hi, lo = np.array([100.0, 100]), np.array([100.0, 100]), np.array([90.0, 100])
pnl, how, ex = simulate_day(op, hi, lo, 100.5, 1, 100.0, 1, 0.0075,
                            cost=0, slip=0, fill_model="gap")
eq("entry_i 之前不掃描 how", how, "close")

# ---- 訊號桶邊界(明確不等式) ----
for s, want in [(-0.021, None), (-0.02, -1), (-0.01, None), (-0.0001, None),
                (0.0, 1), (0.0099, 1), (0.01, 1), (0.0199, 1), (0.02, -1)]:
    eq(f"bucket s={s}", signal_bucket(s)[1], want)
eq("s=0.02 進場時點", signal_bucket(0.02)[2], "1000")
eq("s=-0.02 進場時點", signal_bucket(-0.02)[2], "open")

print(f"\n{'全部通過' if not FAIL else '失敗 ' + str(len(FAIL)) + ' 項:'}")
for f in FAIL:
    print("  " + f)
sys.exit(1 if FAIL else 0)
