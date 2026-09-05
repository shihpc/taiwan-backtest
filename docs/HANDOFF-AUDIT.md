# 交接／檢核文件 — MTX 日內策略回測專案（給外部 AI 審核用）

> 目的：讓一個沒有任何前情的 AI（或人）能獨立**重現、驗證、否證**本專案的全部主張。
> 本文件刻意把弱點與可攻擊面寫在最前面。模擬研究、非投資建議。
> 撰於 2026-09-05；repo：https://github.com/shihpc/taiwan-backtest （公開，raw 可直接抓）
> 網站：https://shihpc.github.io/taiwan-backtest/

## 0. 請優先攻擊的弱點（我方自白）

1. **挖掘深度**：2023–2026 小台資料被同一系列分析反覆使用約 19 輪（scripts/ 的
   analysis2~19 全程留檔）。所有 t 值都是名目值，未做多重比較修正。
2. **規則修剪順序**：playbook 六桶中兩桶（大跌、小跌）是**看過 18 年成績之後**刪除的
   （0/18 與 8/18 正年）。修剪原則「雙時代皆過才留」是原則性的，但時序上屬事後決策。
   對照組：停損/停利掃描（analysis19）的入選標準**先寫死在腳本 docstring 與 README**才跑。
3. **歷史段是近似**：2005–2022 用 TAIEX 加權指數分 K 代替期貨——09:00 開盤（期貨 08:45）、
   13:30 收盤（期貨 13:44）、無成本無滑價無期現價差。它驗的是**方向規則**，不是損益複製。
4. **成本假設**：現代段一律扣 2 點/來回；08:45 開盤價成交、停損觸價即成交均為理想化假設，
   滑價未建模。1 分 K 內同時可觸停損與有利價時，**一律保守先算停損**（tick 級順序不可知）。
5. **樣本外已耗盡**：所有歷史資料都被看過。唯一乾淨檢驗是 2026-09-04 起的前推對帳
   （walkforward/ledger.csv，每日自動記帳，規則凍結）。
6. **費半訊號的可得性**：訊號＝前一晚 ^SOX 收盤報酬（美股 T 日 → 台股 T+1 日）。美股收盤
   為台北 04:00/05:00，早於台股 08:45 開盤，無前視。但實務上依賴 FinMind 美股資料
   在台北早晨已入庫（本系統實測常態 07:30–08:30，見 taiwan-flow-live-v2 的 us 管線紀錄）。

## 1. 現行策略規格（v3-SL，2026-09-04 定版，git 可查凍結時點）

訊號：前一晚費城半導體指數（^SOX）收盤漲跌幅。日期對齊：美股 T 日 → 台股下一交易日
（取 < D 的最近美股日；台股週一對美股週五，已抽查）。

| 前晚 ^SOX | 動作（標的：小台 MTX 日盤） |
|-----------|------|
| < −2% | 空手 |
| −2% ~ −1% | 08:45 開盤市價空 |
| −1% ~ 0% | 空手 |
| 0% ~ +1% | 08:45 開盤市價多 |
| +1% ~ +2% | 08:45 開盤市價多 |
| > +2% | 10:00 市價空 |

出場（三選一）：**停損＝進場價 × 0.75%**（觸價出）→ 否則 **13:44 收盤平**。無停利。
成本 2 點/來回。每日最多一筆單、無隔夜倉。

凍結時點稽核：v3（無停損版）定版＝taiwan-flow-live-v2 commit `167483f`（2026-09-03）；
v3-SL 切換＝本 repo commit `da32160`（2026-09-04）。檢核者可比對 commit 時間戳與
其後 ledger 記帳日期，確認無事後改規則。

## 2. 主張與對應證據

| # | 主張 | 數字 | 重現方式 | 產物 |
|---|------|------|----------|------|
| A | v3-SL 歷史段 2005–2022 十八年逐年皆正 | 總 +59,256 點、18/18 年、最差年 +1,338、MDD −886、最大單虧 −138（未扣成本、TAIEX 近似） | `python3 scripts/analysis19_bracket.py`（看 hist 段 TP0/SL0.75% 列） | `output/v18_bracket_hist.csv` |
| B | v3-SL 現代段 2023–2026 四年皆正 | 總 +16,506、+742/+4,300/+4,473/+6,990、週均 +107、MDD −2,044、最大單虧 −363（扣 2 點） | 同上腳本 modern 段 | `output/v18_bracket_modern.csv` |
| C | 無停損版 v3 為對照 | 現代 +17,492/MDD −3,012；歷史 +53,496/18/18 | `python3 scripts/analysis16_playbook3.py`（應印出「正年=18/18」「正年=4/4」） | `output/v14_longcheck_trades.csv`、`v15_v3b_modern.csv` |
| D | 逐桶 18 年判決（含兩桶翻車） | 漲1~2%多 t=+9.8/18/18；跌−2~−1%空 t=+6.9/17/18；大漲空 t=+2.2/13/18；小漲多 t=+4.7/15/18；小跌多 8/18（刪）；**大跌早盤多 avg −90.3/t=−17.2/0/18（刪）** | `python3 scripts/analysis15_longcheck.py` | `output/v13_allbuckets_trades.csv`（含全六桶；與主張 C 的四桶檔不同） |
| E | 停利有害、停損 0.75% 雙時代穩健 | 停利各檔位單調減損總獲利；SL0.75% 歷史段總獲利 +11%、SL0.5% 於 2022 年僅 +59（否決） | analysis19（20 格全表）＋ `scripts/analysis17_pct_exit.py`/`analysis18_pct_exit_hist.py` | `v18_*`、`v16_pct_exit_modern.csv`、`v17_pct_exit_hist.csv` |
| F | 前推對帳自動運行 | GitHub Actions 台北 21:07/23:07（`.github/workflows/walkforward.yml`），冪等、hour<12 防跨午夜；MDD 停機線 −2,044 | 看 Actions run 歷史（run #1 success） | `walkforward/ledger.csv`（v3-SL，2026-09-04 起）；舊 v3 帳封存 `ledger_v3_nostop.csv`（一筆 2026-09-03 −367） |

註：主張 A~E 的完整演進脈絡（v1 區間逆勢 → 台積電定向 → 費半 playbook 的 19 輪迭代、
各輪為何被否決）在 `README.md`，含每輪的腳本/輸出對照表。

## 3. 資料字典（重現的輸入）

| 檔案 | 內容 | 來源與轉換 |
|------|------|-----------|
| `data/all_bars.parquet` | 小台 1 分 K，2023-08-14~2026-08-20，740 交易日 | FinMind `TaiwanFuturesTick`→近月（排除價差單、當日量最大 contract_date）→1min OHLC。注意：該 dataset 無 `time` 欄，時間在 `date` 欄字串內 |
| `data/all_taiex_bars.parquet` | TAIEX 加權指數 1 分 K，2005-01-03~2022-12-30，4,441 日、1,203,511 列 | FinMind `TaiwanStockKBar` data_id=TAIEX（volume 恆 0 屬正常） |
| `data/us_sox_long.parquet` / `us_sox.parquet` | ^SOX 日線 2004~2022 / 2023-06~ | FinMind `USStockPrice` |
| `data/all_tsmc_morning.parquet`、`us_tsm.parquet` | 台積電早盤分 K、ADR 日線 | 舊版策略（v6~v8）用，現行 playbook **不使用** |
| `data/taiex_daily_agg.csv` | TAIEX 每日聚合值（09:00 開/10:00 價/13:30 收/早盤高低） | 第一次抓取的精簡版，被 all_taiex_bars 取代但保留 |
| `output/*.csv` | 各輪逐筆與彙總 | 各 analysis 腳本產出，檔名前綴對應 README 演進表 |

需重抓資料時：`scripts/mtx_range_fade_backtest.py`（小台 tick，約 45 分）、
`scripts/fetch_taiex_bars.py`（TAIEX 分 K，約 60~90 分）、`scripts/fetch_2330.py`。
皆需環境變數 `FINMIND_TOKEN`（Sponsor 等級）；分析腳本本身**免 token 免網路**。

## 4. 建議檢核清單（依殺傷力排序）

1. **重現主張 A/B/C**：clone 後直接跑 analysis16 與 analysis19（pandas/numpy/pyarrow 即可），
   數字應與本文件第 2 節逐一相符。任何不符都是紅旗。
2. **前視偏誤**：檢查訊號時序（^SOX 收盤 vs 台股開盤）、對齊函式（`np.searchsorted(sd, date) - 1`
   取嚴格早於 D 的最近美股日）、以及 analysis 腳本中是否有任何用到「當日未來資訊」決定進出場之處。
3. **凍結真實性**：用 git log 核對——v3 規則表出現於 2026-09-03 的 commit、v3-SL 於 09-04、
   ledger 首筆記帳日期在其後。若發現規則 commit 晚於其宣稱適用的帳目，即為造假。
4. **同 K 順序假設**：`sim_day`（analysis19）與 `walkforward_daily.py` 的停損判定是否確實保守
   （先停損後有利價）；大漲桶（10:00 進場）的停損掃描是否排除 10:00 前的價格。
5. **腳本與帳冊一致性**：任選 ledger 記帳日，用 `data/all_bars.parquet`（若涵蓋）或 FinMind tick
   手算 v3-SL 損益，與 ledger 對照。已知測例：2026-09-03 小漲桶多單 46,200 進場，
   v3-SL 應為停損 45,853.5、pnl −348.5（舊 v3 無停損版同日為收盤平 −367）。
6. **桶邊界敏感度**：±1%/±2% 是慣例值非優化值（本專案未掃描邊界）。檢核者可自行掃 ±0.5~±2.5%
   看結論是否對邊界脆弱——這是我方沒做、且承認該做的測試。
7. **統計獨立性**：61~651 筆不等的子樣本、每日至多一筆、無重疊持倉，t 值計算為簡單 i.i.d. 假設；
   可自行改用 bootstrap 或 Newey-West 覆核。

## 5. 營運面（檢核範圍外，供理解全貌)

- 前推對帳：workflow 每日自動 append `walkforward/ledger.csv`，網站前端即時渲染；
  累積回落超過 −2,044 點時 log 標 warning＝停機檢討訊號。判讀紀律：跑滿約一季、
  實際分布與回測相符才考慮實單；資金假設 90 萬/1 口（原始保證金 175,250 元，2026-08-12 期交所值）。
- 失敗告警：workflow 失敗自動開 GitHub issue（`.github/actions/notify-failure`）。
- 本 repo 自 taiwan-flow-live-v2/backtest 於 2026-09-04 移出獨立；更早的 git 演進史在該 repo
  （commit 89abffb 起）。

## 6. 一句話總結（供檢核者對照結論）

我方主張的強度排序：**(1) 費半中度行情隔日延續、極端行情隔日反轉的非單調結構**（22 個年度、
兩個獨立市場代理一致）＞ **(2) v3-SL 的正期望**（同資料，含修剪決策）＞ **(3) 具體損益數字**
（理想化成交假設，實際會更差）。檢核者若推翻 (1)，整個專案作廢；若只推翻 (3) 的幅度，
屬預期內。前推帳冊是唯一還沒被看過的裁判。
