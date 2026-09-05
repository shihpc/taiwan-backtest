#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稽核用共用引擎（2026-09-05 audit）— 不修改凍結腳本, 供研究/重現共用
  修正 1: max_drawdown 納入起始權益 0
  修正 2: 成交模型 fill_model="gap" — 逐根帶 open, 跳空穿越停損以「較差的開盤價」成交,
          可配置滑價; tick 取整以不利方向進位(MTX 最小跳動假設 1 點, 見 AUDIT-REPORT 假設節)
  訊號桶: 與 walkforward/walkforward_daily.py 逐字同語意(明確不等式)
"""
import numpy as np

TICK = 1.0  # MTX 最小升降單位假設(待以期交所官方規格佐證)


def signal_bucket(s):
    """回傳 (桶名, 方向 1/-1/None, 進場時點 'open'/'1000'/None)。邊界採半開區間。"""
    if s < -0.02:
        return "大跌<-2%", None, None
    if -0.02 <= s < -0.01:
        return "跌-2~-1%", -1, "open"
    if -0.01 <= s < 0:
        return "小跌-1~0", None, None
    if 0 <= s < 0.01:
        return "小漲0~1%", 1, "open"
    if 0.01 <= s < 0.02:
        return "漲1~2%", 1, "open"
    return "大漲>=2%", -1, "1000"


def max_drawdown(pnls):
    """日結最大回撤, 含起始權益 0。空序列回傳 0.0(語意: 無交易即無回撤)。
    呼叫端負責先按日期排序。"""
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return mdd


def _round_worse(px, direction):
    """停損成交價往不利方向取整到 TICK。多單停損=賣出, 不利=更低; 空單反之。"""
    if direction == 1:
        return np.floor(px / TICK) * TICK
    return np.ceil(px / TICK) * TICK


def simulate_day(op, hi, lo, close_px, entry_i, entry_px, d, sl_pct,
                 cost=2.0, slip=0.0, fill_model="ideal"):
    """單日模擬。回傳 (pnl, how, exit_px)。
    ideal: 觸價即成交於理論停損價(原模型, 供對照)。
    gap:   逐根檢查; 該根 open 已穿越停損 -> 成交於 open(較差價), 否則盤中觸價
           成交於取整後停損價; 兩者皆再加不利滑價 slip。同根先停損的保守規則保留
           (1分K 無法得知 tick 順序)。掃描自 entry_i 起(含進場根)。"""
    sl_amt = entry_px * sl_pct
    if fill_model == "ideal":
        for j in range(entry_i, len(hi)):
            adverse = (entry_px - lo[j]) if d == 1 else (hi[j] - entry_px)
            if adverse >= sl_amt:
                exit_px = entry_px - d * sl_amt
                return -sl_amt - cost, "stop", exit_px
        return (close_px - entry_px) * d - cost, "close", close_px
    # gap 模型
    trigger = entry_px - d * sl_amt                      # 理論觸發價
    stop_fill = _round_worse(trigger, d)                 # 可成交停損價(取整)
    for j in range(entry_i, len(hi)):
        o = op[j]
        gap_through = (o <= trigger) if d == 1 else (o >= trigger)
        if gap_through and j > entry_i:
            exit_px = o - d * slip                       # 以較差的開盤價+不利滑價
            return (exit_px - entry_px) * d - cost, "stop_gap", exit_px
        adverse = (entry_px - lo[j]) if d == 1 else (hi[j] - entry_px)
        if adverse >= sl_amt:
            exit_px = stop_fill - d * slip
            return (exit_px - entry_px) * d - cost, "stop", exit_px
    return (close_px - entry_px) * d - cost, "close", close_px


def simulate_day_full(op, hi, lo, close_px, entry_i, entry_px, d, sl_pct,
                      cost=2.0, slip=0.0, fill_model="gap"):
    """同 simulate_day 但另回傳出場 bar 序號(曝險時間用)。close 出場=最後一根。"""
    sl_amt = entry_px * sl_pct
    trigger = entry_px - d * sl_amt
    stop_fill = _round_worse(trigger, d)
    for j in range(entry_i, len(hi)):
        o = op[j]
        gap_through = (o <= trigger) if d == 1 else (o >= trigger)
        if fill_model == "gap" and gap_through and j > entry_i:
            exit_px = o - d * slip
            return (exit_px - entry_px) * d - cost, "stop_gap", exit_px, j
        adverse = (entry_px - lo[j]) if d == 1 else (hi[j] - entry_px)
        if adverse >= sl_amt:
            if fill_model == "gap":
                exit_px = stop_fill - d * slip
            else:
                exit_px = entry_px - d * sl_amt
            return (exit_px - entry_px) * d - cost, "stop", exit_px, j
    return (close_px - entry_px) * d - cost, "close", close_px, len(hi) - 1
