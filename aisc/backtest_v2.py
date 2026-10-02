# -*- coding: utf-8 -*-
"""v2 回測（規格 v2 §8）：只驗 R1 選股鑑別力與 R2 濾網；進出場沿用「隔日開盤直接買、持有 60 交易日收盤賣」。

主張（回測前寫死，見 config）：
  S1 每日依 R1(ext) 取前 10，後 60 日平均淨報酬 > 候選池全體等權
  S2 R1(ext) 前 10 > R1b(r20) 前 10
  S3 加 R2 濾網的組合：最大回撤更低，且年化報酬 ≥ 不加濾網的 90%
  S4 S1 在樣本外（2026-07-09 起）方向一致（只看方向）
  S5 對照：同 R1 前 10，收盤跌破進場價 15% 隔日開盤出場 vs 固定 60 日（只出數據、不當關卡）
通過條件：全體／台股／美股三組都成立，且樣本數 ≥ 50 的年份至少 2/3 成立（S4 不計年份）。
成本：台股手續費 0.1425%×0.6 雙邊＋證交稅 0.3%；美股每股 US$0.005、最低 US$1。
成交價：訊號日隔一交易日開盤。無前視：所有特徵只用訊號日（含）以前資料。
輸出：output/aisc/v2/<run_id>/ summary.md、各主張表 CSV、equity_*.csv、trades_*.csv（原始明細可重算）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import data as D
from . import indicators as I

# ---------------------------------------------------------------- 成本與單筆交易


def lot_size(market: str) -> int:
    return 1000 if market == "TW" else 1


def shares_for(notional: float, price: float, market: str) -> int:
    lot = lot_size(market)
    return int(notional // (price * lot)) * lot if price > 0 else 0


def net_return(entry: float, exit_: float, shares: int, market: str) -> float | None:
    """含成本的單筆報酬率（相對含買進成本的投入）。shares 為 0 回 None。"""
    if shares <= 0 or entry <= 0:
        return None
    if market == "TW":
        cost_in = entry * shares * (1 + C.TW_FEE_RATE)
        proceeds = exit_ * shares * (1 - C.TW_FEE_RATE - C.TW_TAX_RATE)
    else:
        fee = max(C.US_FEE_MIN, shares * C.US_FEE_PER_SHARE)
        cost_in = entry * shares + fee
        proceeds = exit_ * shares - fee
    return proceeds / cost_in - 1


def forward_trades(df: pd.DataFrame, market: str, hold: int = C.HOLD_DAYS,
                   notional: float | None = None, stop_pct: float | None = None) -> pd.DataFrame:
    """對單一標的，算出以每一列為「訊號日」的交易結果（隔日開盤進、hold 根 K 後收盤出）。
    回傳與 df 等長的表：entry_date, exit_date, net_ret, bars_held, trade_mdd（進場後收盤相對進場價最大跌幅），
    無法完成（資料不足／股數為 0）者為 NaN。stop_pct 給定時：收盤跌破進場價×(1−stop) 隔日開盤出場。"""
    n = len(df)
    notional = notional or C.BT_CAPITAL[market] / C.TOP_N
    o = df["open"].to_numpy(float); c = df["close"].to_numpy(float); dates = df["date"].to_numpy()
    ret = np.full(n, np.nan); held = np.full(n, np.nan); mdd = np.full(n, np.nan)
    ed = np.full(n, None, dtype=object); xd = np.full(n, None, dtype=object)
    for i in range(n):
        e = i + 1; x = e + hold
        if x >= n:
            break
        entry = o[e]
        if not np.isfinite(entry) or entry <= 0:
            continue
        sh = shares_for(notional, entry, market)
        exit_i, exit_px = x, c[x]
        if stop_pct is not None:
            thr = entry * (1 - stop_pct)
            path = c[e:x]                     # 進場日起、出場日前一日止的收盤
            hit = np.where(path < thr)[0]
            if hit.size:
                k = e + hit[0] + 1            # 隔日開盤
                exit_i, exit_px = k, o[k]
        r = net_return(entry, exit_px, sh, market)
        if r is None or not np.isfinite(exit_px):
            continue
        ret[i] = r; held[i] = exit_i - e
        mdd[i] = min(0.0, float(np.nanmin(c[e:exit_i + 1]) / entry - 1))
        ed[i] = dates[e]; xd[i] = dates[exit_i]
    return pd.DataFrame({"entry_date": ed, "exit_date": xd, "net_ret": ret, "bars_held": held, "trade_mdd": mdd})


# ---------------------------------------------------------------- 面板


def build_panel(prices: dict, market: str, uni: dict, stop_pct: float | None = None) -> dict[str, pd.DataFrame]:
    """每檔：特徵 + 前瞻交易結果（固定 60 日）＋（S5）停損版。"""
    panel = {}
    for code in C.universe_codes(uni, market):
        df = prices.get((market, code))
        if df is None or len(df) < C.MA_LONG + 2:
            continue
        f = I.add_features(df)
        fw = forward_trades(df, market)
        f["net_ret"] = fw["net_ret"]; f["entry_date"] = fw["entry_date"]; f["exit_date"] = fw["exit_date"]
        f["trade_mdd"] = fw["trade_mdd"]
        if stop_pct is not None:
            fs = forward_trades(df, market, stop_pct=stop_pct)
            f["net_ret_stop"] = fs["net_ret"]; f["bars_stop"] = fs["bars_held"]; f["trade_mdd_stop"] = fs["trade_mdd"]
        f["code"] = code
        panel[code] = f.set_index("date", drop=False)
    return panel


def by_date(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把面板轉成 {訊號日: 當日各檔一列} 的字典（一次 groupby，供訊號層與組合層共用）。"""
    if not panel:
        return {}
    big = pd.concat(panel.values(), ignore_index=True)
    return {d: g.reset_index(drop=True) for d, g in big.groupby("date", sort=True)}


def picks_by_date(bd: dict[str, pd.DataFrame], market: str, score: str = "ext") -> dict[str, list[str]]:
    """每個訊號日的 R1 名單（依 score 前 10，不看是否能完成交易）。"""
    out = {}
    for d, snap in bd.items():
        s = snap[snap[score].notna()]
        out[d] = list(I.rank_candidates(s, market, score)["code"]) if not s.empty else []
    return out


def market_dates(panel: dict, start: str = C.SAMPLE_START) -> list[str]:
    s = set()
    for f in panel.values():
        s.update(f.index[f.index >= start])
    return sorted(s)


# ---------------------------------------------------------------- 訊號層（S1／S2／S4／S5）


def signal_level(bd: dict[str, pd.DataFrame], market: str, dates: list[str]) -> pd.DataFrame:
    """每個訊號日：R1 前 10／R1b 前 10／全體等權 的平均淨報酬，以及 S5 停損版。只計能完成的交易。"""
    out = []
    for d in dates:
        snap = bd.get(d)
        if snap is None:
            continue
        done = snap[snap["net_ret"].notna()]
        if done.empty:
            continue
        r1 = I.rank_candidates(done, market, "ext")
        r1b = I.rank_candidates(done, market, "r20")
        row = {"date": d, "market": market, "n_all": len(done), "all_mean": done["net_ret"].mean(),
               "n_r1": len(r1), "r1_mean": r1["net_ret"].mean() if len(r1) else np.nan,
               "n_r1b": len(r1b), "r1b_mean": r1b["net_ret"].mean() if len(r1b) else np.nan,
               "r1_codes": ",".join(r1["code"])}
        if "net_ret_stop" in done and len(r1):
            row["r1_stop_mean"] = r1["net_ret_stop"].mean()
            row["r1_mdd_mean"] = r1["trade_mdd"].mean(); row["r1_stop_mdd_mean"] = r1["trade_mdd_stop"].mean()
            row["r1_stop_bars"] = r1["bars_stop"].mean()
        out.append(row)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- 組合層（S3／S5 的回撤與淨值）


def simulate_portfolio(panel: dict, market: str, dates: list[str], bench: pd.DataFrame | None,
                       use_r2: bool, stop_pct: float | None = None, slots: int = C.TOP_N,
                       picks: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """等權槽位組合：每日訊號 → 隔日開盤補滿空槽（依 R1 名次、已持有不加碼）→ 持有 hold 日收盤出場。
    use_r2：訊號日大盤 C<MA60 時不開新倉。stop_pct：收盤跌破進場價 15% 隔日開盤出場。
    回傳逐日 equity（起點 1.0）。"""
    capital = C.BT_CAPITAL[market]; per = capital / slots
    r2_off = I.r2_filter(bench) if (use_r2 and bench is not None and not bench.empty) else None
    idx = {code: {d: i for i, d in enumerate(f.index)} for code, f in panel.items()}
    arrays = {code: (f["open"].to_numpy(float), f["close"].to_numpy(float)) for code, f in panel.items()}
    picks = picks if picks is not None else picks_by_date(by_date(panel), market, "ext")
    cash = capital; pos: dict[str, dict] = {}; pending: list[str] = []
    last_close: dict[str, float] = {}
    eq = []
    for d in dates:
        # 1) 今日開盤：先處理停損出場（昨日收盤已觸發）、再補新倉
        for code in list(pos):
            p = pos[code]
            if p.get("stop_flag") and d in idx[code]:
                i = idx[code][d]; px = arrays[code][0][i]
                if np.isfinite(px):
                    cash += _sell_proceeds(px, p["shares"], market); del pos[code]
        for code in pending:
            if len(pos) >= slots or code in pos or d not in idx[code]:
                continue
            i = idx[code][d]; px = arrays[code][0][i]
            if not np.isfinite(px):
                continue
            sh = shares_for(per, px, market)
            cost = _buy_cost(px, sh, market)
            if sh <= 0 or cost > cash:
                continue
            cash -= cost
            pos[code] = {"shares": sh, "entry": px, "exit_i": i + C.HOLD_DAYS, "entry_date": d}
        pending = []
        # 2) 今日收盤：到期出場、停損判定、市值
        for code in list(pos):
            p = pos[code]
            if d not in idx[code]:
                continue
            i = idx[code][d]; cl = arrays[code][1][i]
            if np.isfinite(cl):
                last_close[code] = cl
            if i >= p["exit_i"] and np.isfinite(cl):
                cash += _sell_proceeds(cl, p["shares"], market); del pos[code]; continue
            if stop_pct is not None and np.isfinite(cl) and cl < p["entry"] * (1 - stop_pct):
                p["stop_flag"] = True
        mv = sum(p["shares"] * last_close.get(code, p["entry"]) for code, p in pos.items())
        eq.append({"date": d, "equity": (cash + mv) / capital, "n_pos": len(pos)})
        # 3) 今日收盤後的訊號 → 明日開盤
        blocked = bool(r2_off.get(d, False)) if r2_off is not None else False
        if not blocked:
            pending = [c for c in picks.get(d, []) if c not in pos]
    return pd.DataFrame(eq)


def _buy_cost(px, sh, market):
    if market == "TW":
        return px * sh * (1 + C.TW_FEE_RATE)
    return px * sh + max(C.US_FEE_MIN, sh * C.US_FEE_PER_SHARE)


def _sell_proceeds(px, sh, market):
    if market == "TW":
        return px * sh * (1 - C.TW_FEE_RATE - C.TW_TAX_RATE)
    return px * sh - max(C.US_FEE_MIN, sh * C.US_FEE_PER_SHARE)


def equity_stats(eq: pd.DataFrame) -> dict:
    if eq.empty:
        return {"cagr": np.nan, "mdd": np.nan, "total": np.nan, "days": 0}
    e = eq["equity"].to_numpy(float)
    peak = np.maximum.accumulate(e); mdd = float(np.min(e / peak - 1))
    years = max(len(e) / 252, 1e-9)
    cagr = float(e[-1] ** (1 / years) - 1) if e[-1] > 0 else -1.0
    return {"cagr": cagr, "mdd": mdd, "total": float(e[-1] - 1), "days": len(e)}


# ---------------------------------------------------------------- 判定（純函式，可離線測）


def year_of(d: str) -> int:
    return int(str(d)[:4])


def claim_rows_signal(sig: pd.DataFrame, a: str, b: str, n_col: str) -> pd.DataFrame:  # noqa: C901
    """依 group（全體／TW／US）與年份切片，比較訊號層兩個平均欄位 a > b。"""
    rows = []
    def add(label, df, year=None):
        if df.empty:
            return
        n = int(df[n_col].sum())
        rows.append({"group": label, "year": year if year is not None else "all", "n": n,
                     a: df[a].mean(), b: df[b].mean(), "diff_pp": (df[a].mean() - df[b].mean()) * 100,
                     "pass": bool(df[a].mean() > df[b].mean())})
    for label, df in [("全體", sig), ("TW", sig[sig["market"] == "TW"]), ("US", sig[sig["market"] == "US"])]:
        add(label, df)
        for y, g in df.groupby(df["date"].map(year_of)):
            add(label, g, int(y))
    return pd.DataFrame(rows, columns=["group", "year", "n", a, b, "diff_pp", "pass"])


def verdict(table: pd.DataFrame, min_n: int = C.MIN_YEAR_SAMPLES, frac: float = C.YEAR_PASS_FRAC) -> dict:
    """三組全體列皆 pass，且（三組合計）樣本數 ≥ min_n 的年份列至少 frac 通過。"""
    if table.empty:
        return {"pass": False, "reason": "無資料"}
    allrows = table[table["year"] == "all"]
    groups_ok = bool(len(allrows) == 3 and allrows["pass"].all())
    yrs = table[(table["year"] != "all") & (table["n"] >= min_n)]
    yr_ok = bool(len(yrs) == 0 or yrs["pass"].mean() >= frac)
    return {"pass": groups_ok and yr_ok, "groups_ok": groups_ok, "years_ok": yr_ok,
            "years_pass": int(yrs["pass"].sum()), "years_total": int(len(yrs))}


# ---------------------------------------------------------------- 主流程


def run(prices: dict, benches: dict, uni: dict, out_dir: Path, markets=("TW", "US"), oos_start: str = C.OOS_START) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    sig_all, eq_rows, trades = [], [], []
    stats = {}
    for m in markets:
        panel = build_panel(prices, m, uni, stop_pct=C.STOP_LOSS_PCT)
        if not panel:
            continue
        dates = market_dates(panel)
        bd = by_date(panel); pk = picks_by_date(bd, m, "ext")
        sig = signal_level(bd, m, dates); sig_all.append(sig)
        for use_r2 in (False, True):
            for stop in (None, C.STOP_LOSS_PCT):
                eq = simulate_portfolio(panel, m, dates, benches.get(m), use_r2, stop, picks=pk)
                key = f"{m}_r2{int(use_r2)}_stop{int(stop is not None)}"
                eq.to_csv(out_dir / f"equity_{key}.csv", index=False)
                stats[key] = equity_stats(eq)
                stats[key]["yearly"] = _yearly_stats(eq)
                eq_rows.append((key, eq))
        # 原始明細：每檔每訊號日的特徵與前瞻結果（驗收可重算）
        pd.concat(panel.values()).reset_index(drop=True).to_csv(out_dir / f"trades_{m}.csv", index=False)
    sig = pd.concat(sig_all, ignore_index=True) if sig_all else pd.DataFrame()
    sig.to_csv(out_dir / "signal_daily.csv", index=False)
    res = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "oos_start": oos_start}
    ins = sig[sig["date"] < oos_start]; oos = sig[sig["date"] >= oos_start]
    s1 = claim_rows_signal(ins, "r1_mean", "all_mean", "n_r1"); s1.to_csv(out_dir / "S1.csv", index=False)
    s2 = claim_rows_signal(ins, "r1_mean", "r1b_mean", "n_r1"); s2.to_csv(out_dir / "S2.csv", index=False)
    s4 = claim_rows_signal(oos, "r1_mean", "all_mean", "n_r1"); s4.to_csv(out_dir / "S4.csv", index=False)
    res["S1"] = verdict(s1); res["S2"] = verdict(s2)
    s4all = s4[s4["year"] == "all"]
    res["S4"] = {"pass": bool(len(s4all) == 3 and s4all["pass"].all()), "n_signal_days": int(len(oos)),
                 "note": "只看方向；樣本外交易須已完成 60 日才計入"}
    res["S3"] = _s3(stats, markets); res["S5"] = _s5(ins, stats, markets)
    res["portfolio_stats"] = stats
    (out_dir / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=_j), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_summary(res, s1, s2, s4), encoding="utf-8")
    return res


def _j(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _yearly_stats(eq: pd.DataFrame) -> dict:
    out = {}
    if eq.empty:
        return out
    for y, g in eq.groupby(eq["date"].map(year_of)):
        e = g["equity"].to_numpy(float); base = e[0]
        peak = np.maximum.accumulate(e)
        out[int(y)] = {"ret": float(e[-1] / base - 1), "mdd": float(np.min(e / peak - 1)), "days": len(e)}
    return out


def _s3(stats: dict, markets) -> dict:
    """S3：加 R2 後 MDD 更低且 CAGR ≥ 不加的 90%（CAGR 為負時改為不低於不加濾網減 10% 絕對值）。"""
    rows = []
    for m in markets:
        a, b = stats.get(f"{m}_r21_stop0"), stats.get(f"{m}_r20_stop0")
        if not a or not b:
            continue
        rows.append({"group": m, "year": "all", "cagr_r2": a["cagr"], "cagr_base": b["cagr"], "mdd_r2": a["mdd"], "mdd_base": b["mdd"],
                     "pass": _s3_pass(a["cagr"], b["cagr"], a["mdd"], b["mdd"])})
        for y in sorted(set(a["yearly"]) & set(b["yearly"])):
            ay, by = a["yearly"][y], b["yearly"][y]
            rows.append({"group": m, "year": str(y), "ret_r2": ay["ret"], "ret_base": by["ret"], "mdd_r2": ay["mdd"],
                         "mdd_base": by["mdd"], "pass": _s3_pass(ay["ret"], by["ret"], ay["mdd"], by["mdd"])})
    groups = [r for r in rows if r["year"] == "all"]
    return {"pass": bool(groups and all(r["pass"] for r in groups) and len(groups) == len(markets)),
            "rows": rows, "note": "全體＝各市場皆須通過；年份列供參考"}


def _s3_pass(c_r2, c_base, m_r2, m_base) -> bool:
    if any(map(lambda v: v is None or (isinstance(v, float) and math.isnan(v)), (c_r2, c_base, m_r2, m_base))):
        return False
    ret_ok = c_r2 >= c_base * 0.9 if c_base >= 0 else c_r2 >= c_base - 0.1 * abs(c_base)
    return bool(m_r2 > m_base and ret_ok)


def _s5(ins: pd.DataFrame, stats: dict, markets) -> dict:
    rows = []
    for label, df in [("全體", ins), *[(m, ins[ins["market"] == m]) for m in markets]]:
        if df.empty or "r1_stop_mean" not in df:
            continue
        rows.append({"group": label, "r1_fixed60_mean": df["r1_mean"].mean(), "r1_stop15_mean": df["r1_stop_mean"].mean(),
                     "trade_mdd_fixed": df["r1_mdd_mean"].mean(), "trade_mdd_stop": df["r1_stop_mdd_mean"].mean(),
                     "avg_bars_stop": df["r1_stop_bars"].mean()})
    port = {m: {"fixed": {k: v for k, v in stats.get(f"{m}_r20_stop0", {}).items() if k != "yearly"},
                "stop": {k: v for k, v in stats.get(f"{m}_r20_stop1", {}).items() if k != "yearly"}} for m in markets}
    return {"rows": rows, "portfolio": port, "note": "對照資料，不當關卡；供決定停損是否排進 v3"}


def render_summary(res: dict, s1: pd.DataFrame, s2: pd.DataFrame, s4: pd.DataFrame) -> str:
    L = [f"# v2 回測結果（{res['generated_at']}）", "",
         "模擬研究、含成本、隔日開盤成交；不是投資建議。通過條件：全體／TW／US 皆成立且樣本 ≥ 50 的年份 ≥ 2/3 成立。", ""]
    for k in ("S1", "S2", "S3", "S4"):
        v = res[k]; L.append(f"- **{k}**：{'✅ 通過' if v.get('pass') else '❌ 未通過'}  "
                             + json.dumps({kk: vv for kk, vv in v.items() if kk not in ('rows',)}, ensure_ascii=False, default=_j))
    L += ["", "## S1：R1(ext) 前 10 vs 全體等權（樣本內）", "", _md(s1),
          "", "## S2：R1(ext) vs R1b(r20)（樣本內）", "", _md(s2),
          "", "## S4：樣本外（只看方向）", "", _md(s4),
          "", "## S3：R2 濾網（組合層）", "", _md(pd.DataFrame(res["S3"]["rows"])),
          "", "## S5：停損 15% 對照（不當關卡）", "", _md(pd.DataFrame(res["S5"]["rows"])),
          "", "組合層統計（r2=濾網, stop=停損）：", "",
          _md(pd.DataFrame([{"key": k, **{kk: vv for kk, vv in v.items() if kk != 'yearly'}} for k, v in res["portfolio_stats"].items()]))]
    return "\n".join(L)


def _md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "（無資料）"
    d = df.copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
    cols = list(d.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in d.itertuples(index=False)]
    return "\n".join(out)


# ---------------------------------------------------------------- 合成資料（離線煙霧測試）


def synthetic_prices(uni: dict, n_days: int = 900, seed: int = 7, start: str = "2021-01-04") -> tuple[dict, dict]:
    rng = np.random.default_rng(seed)
    bdays = pd.bdate_range(start, periods=n_days).strftime("%Y-%m-%d").tolist()
    def mk(mu, sigma, p0, vol):
        r = rng.normal(mu, sigma, n_days); c = p0 * np.exp(np.cumsum(r))
        o = c * (1 + rng.normal(0, sigma / 3, n_days)); h = np.maximum(o, c) * (1 + abs(rng.normal(0, sigma / 2, n_days)))
        l = np.minimum(o, c) * (1 - abs(rng.normal(0, sigma / 2, n_days))); v = rng.integers(vol, vol * 5, n_days)
        return pd.DataFrame({"date": bdays, "open": o, "high": h, "low": l, "close": c, "volume": v, "amount": c * v})
    prices, benches = {}, {}
    for m in ("TW", "US"):
        for code in C.universe_codes(uni, m):
            prices[(m, code)] = mk(rng.normal(0.0004, 0.0003), rng.uniform(0.015, 0.035),
                                   rng.uniform(50, 800), 2_000_000 if m == "TW" else 500_000)
        benches[m] = mk(0.0003, 0.012, 15000 if m == "TW" else 4000, 1)
    return prices, benches


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="用合成價格跑完整流程（離線煙霧測試，結果無意義）")
    ap.add_argument("--offline", action="store_true", help="只讀 parquet 快取、不打 FinMind")
    ap.add_argument("--market", choices=["TW", "US"], action="append")
    ap.add_argument("--out", help="輸出目錄（預設 output/aisc/v2/<時戳>）")
    a = ap.parse_args(argv)
    uni = C.load_universe()
    markets = tuple(a.market) if a.market else ("TW", "US")
    if a.synthetic:
        prices, benches = synthetic_prices(uni)
        out = Path(a.out or (C.OUTPUT_DIR / "v2" / "synthetic"))
    else:
        prices = D.load_all(uni, markets, refresh=not a.offline)
        benches = {m: D.load_benchmark(m, uni, refresh=not a.offline) for m in markets}
        out = Path(a.out or (C.OUTPUT_DIR / "v2" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")))
    res = run(prices, benches, uni, out, markets)
    print((out / "summary.md").read_text(encoding="utf-8")[:3000])
    print(f"\n輸出目錄：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
