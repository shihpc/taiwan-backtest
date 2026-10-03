# aisc — AI 供應鏈選股與下單系統（Phase 0）

規格正本：Claude Docs「AI 供應鏈選股與下單系統規格 v2」（2026-10-03 拍板版）。本目錄只實作 **Phase 0**：
不產委託單、不送單；所有判讀屬 AI 研判、非投資保證。

| 模組 | 對應規格 | 說明 |
|---|---|---|
| `universe.json` | §2 | 候選池凍結 117 檔（台股 93＝postmkt `screen.json` 2026-10-02 快照、美股 24）＋大盤基準（TAIEX／^SOX）。增減要記 `changes` |
| `config.py` | §3／§4／§5／§8 | 全部門檻常數（MA20/60、ATR14、前 10、R3 門檻、H=60、成本、樣本外切點）。**回測前寫死，要改＝v3** |
| `data.py` | §2 | FinMind `TaiwanStockPriceAdj`／`USStockPrice` → 統一欄位、逐檔 parquet 增量快取（`data/aisc/prices/`，不進 git）。token 走 `FINMIND_TOKEN`，log 一律遮罩 |
| `indicators.py` | §3 | 純函式：ext、r5、r20、MA60 上下、slope60、liq20、R2 濾網、R1 排序（同分依代號） |
| `daily_table.py` | §3 末段、§9 Phase 0 | 每日描述表 → `output/aisc/daily/<date>.{csv,md}`，`--push` 推 LINE。R1 名單只標「待回測」 |
| `backtest_v2.py` | §8 | S1–S5：訊號層（隔日開盤進、60 日收盤出、含成本）＋組合層（10 槽等權、R2 有無、停損對照）；判定三組＋年份 2/3；輸出 `output/aisc/v2/<run>/`（`trades_*.csv` 為可重算的原始明細） |
| `ibkr_flex.py` | §6／§9 | IBKR Flex Web Service 唯讀報表（SendRequest→GetStatement），存 `$AISC_PRIVATE_DIR/ibkr`，不進 repo |
| `fubon_account.py` | §6／§9 | 富邦 `fubon_neo` 唯讀庫存骨架；**SDK 方法名未在真 SDK 上實跑，標 TODO** |
| `notify.py` | §7 | LINE Messaging API push（`LINE_TOKEN`／`LINE_USER_ID`，與 Worker 同通道） |
| `tests/test_core.py` | — | 14 項離線測試（免 token）：無前視、成本、停損路徑、排序 tie-break、判定規則、端到端合成資料 |
| `../tools/aisc_cron.sh` | §9 | Hetzner cron 入口：每日表＋LINE＋commit `output/aisc/daily` |

## 指令

```bash
python3 aisc/tests/test_core.py                 # 離線測試（或 python3 -m pytest aisc/tests -q）
python3 -m aisc.backtest_v2 --synthetic         # 合成資料煙霧測試（約 40 秒，結果無意義）
FINMIND_TOKEN=… python3 -m aisc.daily_table     # 每日描述表（首次會抓 2021 起全史，117 檔約 240 次請求）
FINMIND_TOKEN=… python3 -m aisc.backtest_v2     # 真實 v2 回測 → output/aisc/v2/<時戳>/summary.md
python3 -m aisc.backtest_v2 --offline           # 只讀快取重跑
IBKR_FLEX_TOKEN=… IBKR_FLEX_QUERY_ID=… python3 -m aisc.ibkr_flex
```

## 實作口徑（規格沒寫死、這裡定的，回測後不得回頭改）

- **ATR14**＝真實波幅 14 日簡單平均；**slope60**＝MA60 − 5 日前 MA60（純描述欄位）。
- **持有 60 交易日**：訊號日 t → 進場 t+1 開盤 → 出場 t+61 收盤（進場後第 60 根 K 收盤）。
- **成本**：台股淨報酬＝賣出×(1−0.1425%×0.6−0.3%) ÷ 買進×(1+0.1425%×0.6) − 1；美股每邊 max(US$1, 股數×0.005)。
  股數＝名目資金（總資金÷10）整張／整股；湊不到一張（股）的交易不計。
- **S1／S2／S4 訊號層**：每個訊號日，R1 前 10 與「全體等權」都只計**能完成 60 日**的交易（尾端未完成者兩邊同時排除）。
  年份切片的樣本數＝該年 R1 交易筆數。
- **S3 組合層**：10 槽等權、**每槽名目＝當下淨值÷10**（2026-10-03 驗收後改，原為初始資金÷10 使後期曝險只剩三成）、已持有不加碼、訊號日 R2 關閉則隔日不開新倉；MDD 取逐日淨值；CAGR 以 252 日年化。
  年份列只供參考，S3 通過＝各市場整段皆通過。
- **S5**：收盤跌破進場價 15% → 隔日開盤出場；同時給訊號層平均報酬／單筆回撤與組合層 MDD，不當關卡。
- **樣本外 S4**：訊號日 ≥ 2026-07-09 且交易已完成 60 日者才計入，只看三組方向；一筆都沒完成時標「無樣本」而非「未通過」。
- **資料清理**（`data.clean()`，讀出時套用、快取存原始列）：volume=0 的列整列剔除（上游非交易佔位列，實查 99 列、含 6691 2021-03-10 未還原 open）；open 落在 [low, high] 外者夾回區間（實查 1,704 列、偏離中位數 0.6%，集中在前興櫃代號）。

## v2 回測結論（2026-10-03，三次實跑，定版＝`output/aisc/v2/20261003_155628/`，commit f40663a）

| 主張 | 結果 | 關鍵數字 |
|---|---|---|
| S1 R1(ext) 前 10 > 全體等權 | ❌ | 全體 +0.68pp、TW +2.30pp、**US −0.97pp**；年份 11/18（<2/3） |
| S2 R1(ext) > R1b(r20) | ❌ | 三組 r20 皆略勝 ext（−0.62～−0.67pp）；年份 4/18 |
| S3 加 R2 濾網 MDD 更低且 CAGR ≥ 90% | ❌ | TW 通過（MDD −36% vs −47%、CAGR 40.3% vs 41.2%）；**US 反而更差**（MDD −54.5% vs −36.4%、CAGR 26% vs 44%） |
| S4 樣本外方向 | ⚪ 無樣本 | 資料止於 2026-10-02，2026-07-09 起無一筆走完 60 日 |
| S5 停損 15% 對照 | 數據 | 訊號層：固定 60 日 11.9% vs 停損 9.0%；組合層 TW 停損 CAGR 53% vs 41%、MDD −36% vs −47%；US 停損 35% vs 44%、MDD −42% vs −36%（兩市場方向相反） |

**依規格 §8：R1 與 R2 不上線**。三次實跑的差異：第一次（24455b4）為釘死名目的舊引擎；第二次（5fd923d）換當下淨值但 ^SOX 被 clean() 清空、US 濾網失效；
第三次（f40663a）修正後定版——S1／S2 表三次逐字相同，S3 的 US 結論與第一次同向。
US R2 失效的機制（fresh-context 驗收於第一次產物確認、非程式錯）：2022 年 SOX 低於 MA60 共 178/251 日，放行窗只有五段短反彈，
放行當天一次補滿 10 槽（3/25 買 10 檔 60 日後全虧均 −26%、7/21 買 8 檔均 −26%），真正 V 轉時又空手。
**r20 勝過 ext 是對照組的事後發現，不是預先登錄主張，不得直接換上；要用就寫成 v3 主張、以 2026-07-09 起的樣本外驗。**
驗收：第一次產物由 fresh-context subagent 以原始欄位重算指標／交易／S 表／淨值曲線全部一致（含 2022 年 US 濾網路徑逐日對跑）；
第三次相對第二次只動基準清理，S1／S2／TW 四條曲線／US 不加濾網兩條曲線與第二次逐位相同，US 加濾網兩條與第一次同形（分岔日 2022-03-18、2022 谿底 0.577 vs 0.574）。

## 未完成／待使用者

- 本沙箱無 `FINMIND_TOKEN`，**真實資料未跑過**；首次跑會 240 次請求（117 檔×2 來源不等），FinMind 額度請留意。
- 台股 93 檔取 postmkt `screen.json` 10/2 快照，與 v1 回測的 93 檔是否逐檔相同待確認。
- 規格 §6 寫「美股 7 檔走 IBKR」但 §2 美股 24 檔，兩處不一致，候選池以 §2 為準。
- `fubon_account.py` 須在裝了 `fubon_neo` 的本機對照 SDK README 校正方法名。
- 合規確認（Phase 0 第 1 項）是人工事項。
