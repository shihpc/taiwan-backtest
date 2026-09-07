# CLAUDE.md — taiwan-backtest 接手速覽

<!-- CANON:BEGIN v1 -->
<!-- 唯一事實來源＝shihpc/claude-harness 的 CANON.md。以下區塊在六個 repo 的 CLAUDE.md 頂端
     有 byte-identical 逐字副本，由各 repo 的 .github/workflows/canon.yml 守門（比對 sha256）。
     改動流程：先改 claude-harness/CANON.md → 跑 tools/sync_canon.py 同步六份 → 更新守門 hash。
     不要只改單一 repo，CI 會擋下來。 -->

## 通用工作鐵律（六個 repo 逐字相同，勿單獨修改）

1. **機密**：token／金鑰只存在不受版控的本機設定或受控 secrets（`.env`／Actions secret／
   `wrangler secret`），絕不寫進會 commit 的檔案、log 或對話輸出。commit 前掃 staged 內容，
   **只回報檔名／行號／類型、不把可疑字串原文印出來**；`sk-ant-`／`ghp_`／`eyJ` 是線索不是全集。
2. **指揮官不下場**：掃 repo、通讀 >300 行的檔、一次讀 >3 個檔、查網頁研究、批次改檔、
   驗收改過的東西——這六類一律派 subagent，主對話只收結論＋`檔案:行號`；但 subagent 回報
   **不等於事實**，主對話為核對結論可直接查原始證據。雲端 session 的 subagent 派工（含第 3 條
   驗收）已獲常備授權，需要時直接派，不需逐次詢問。
3. **先寫驗收條件再動手**：動手前先寫下目標專案完整路徑＋怎樣算完成＋怎麼驗。修改者先自測，
   再派 fresh-context subagent 驗收——**改東西的 agent（含主對話自己）不得擔任驗收者**。
   驗收要綁**確切 commit／產物版本**；驗收後又改動，受影響部分要重驗。
4. **不確定不亂說**：陳述事實（尤其技術細節、數字、外部服務的限制與行為）要嘛附佐證（官方
   文件、實測、`檔案:行號`），要嘛明說「這點我不確定，需要查證」，不可憑印象當確定講。區分
   「已驗證事實」與「推測」，推測要標明；**`檔案:行號` 只證明程式這樣寫，不證明線上這樣跑**。
5. **一次只做一件事**：聚焦一個明確目標，完成該目標必要的修改、測試與整合；不擅自加入無關
   重構或延伸功能。範圍外問題簡短記錄、不自行擴張任務。
6. **完成的定義**：驗收條件逐條打勾＋fresh-context subagent 驗過＋產物在使用者拿得到的位置，
   並明示已完成與未完成；**可執行的東西沒實跑過不算完成**（純文件交付以內容與結構檢查為準）。
   涉及部署者另需 push＋部署 workflow 成功＋在**實際服務的位置**驗證本次變更（線上頁面／API／
   資料時戳）——**raw URL 只證明原始碼進了 repo，不證明線上跑的是該版本**，200 也不等於功能正確。
7. **push 前**：先確認目前分支與推送目標，`git fetch` 後檢查遠端是否領先，非空必須先看內容
   （訊息／時間戳／diff）。一般 push → rebase 整合（本專案既定政策），嚴禁直接覆蓋；force push
   前若遠端領先的 commit 是真實新工作 → 停下來問，且一律用 `--force-with-lease=<ref>:<預期 SHA>`；
   授權「這次 force push」不等於授權蓋掉遠端所有領先 commit。
8. **新指標／訊號若會影響投資方向、候選排序、進出場或風險判定，先問有沒有回測依據**，沒有就
   先驗證再上線；純描述性顯示（欄位、日期、圖示）只需驗算式正確。市場內容可做情境判讀與多空
   因素分析，可研判市場與大眾情緒對該數值或新聞的可能反應，並可提供具體個股／標的的買賣建議
   與進出點位；以上均須附依據、區分事實與推論，並標明屬 AI 研判而非保證。
9. **語言**：對話與文件用繁體中文；程式碼註解可中文，identifier 用英文；外部原文、API 名稱、
   指令與錯誤訊息保留原樣。

> 判準細則、派工模板、教訓簿見 `shihpc/claude-harness`（private）。雲端 session 需 add_repo 才讀得到。
<!-- CANON:END v1 -->

小台（MTX）日內策略回測站：**回測研究（`scripts/`＋`output/`）＋獨立稽核（`audit/`）
＋每日模擬前推對帳（`walkforward/`）＋單檔靜態前端 `index.html`**，GitHub Pages 從 main root 服務。
線上 https://shihpc.github.io/taiwan-backtest/ 。**2026-09-07 起納入受管 repo**（家族第六個 CANON 副本）。
**站上一切績效數字都是模擬研究、不是投資建議**；現行策略 Playbook v3-SL 的完整脈絡見 `README.md`
（頂部有「閱讀前必看：本文若干績效敘述已於 2026-09-05 稽核降級」導讀表），稽核原文見
`audit/AUDIT-REPORT.md`、外部五年驗證見 `docs/FIVEYEAR-VALIDATION-CHATGPT.md`。

## 佈局

- `index.html`（單檔、CSS/JS 內嵌，**無 build 工具**）：三個區塊 `id="sec-backtest"`（回測驗證，
  內含 `id="sec-credibility"` 降級卡與 `id="sec-audit"` 稽核摘要卡）／`id="sec-params"`（策略參數表）／
  `id="sec-ledger"`（前推對帳，`renderLedger` 產出）。**唯一的網路請求是同源
  `fetch('walkforward/ledger.csv?t='+Date.now(),{cache:'no-store'})`**——不打任何外部 API，
  也**沒有**家族另四站的 `loadSiteVer()`／`callClaude`／`mdToHtml`／`ghSaveAnalysis` 等跨站同步碼
  （2026-09-07 全 repo grep 零命中），所以**不納入 `claude-harness/tools/check_sync.py`**。
  動態值一律過 `function esc(s)` 才進 `innerHTML`。
- `walkforward/`：**唯一每日會跑的東西**。`walkforward_daily.py`（正式帳冊 `ledger.csv`，規則
  v3-SL，2026-09-04 定版、註解自述「不得回頭改」；舊無停損版封存於 `ledger_v3_nostop.csv`）＋
  `shadow_daily.py`（影子對照帳冊 `ledger_shadow_1rbe.csv`／`ledger_shadow_1rbe_ts.csv`，規格
  `SHADOW-SPEC.md`，首日 2026-09-07，**只觀察不影響正式策略**）＋離線測試 `test_shadow.py`。
- `scripts/`：`analysis2.py`~`analysis19_bracket.py` 的研究腳本序列（全程留檔，刻意保留挖掘軌跡）
  ＋ `fetch_*.py`／`mtx_range_fade_backtest.py` 取數腳本（需 `FINMIND_TOKEN` Sponsor）。
- `output/`：上述腳本的結果 CSV（`v2_results.csv`…`v18_bracket_modern.csv` 等）。
- `audit/`：2026-09-05 獨立稽核——`AUDIT-REPORT.md`（報告）、`engine.py`（獨立重現引擎）、
  `run_*.py`、`research_spec.md`（事前判準）、`tests_audit.py`（離線回歸測試）、`out/`（稽核產出）。
- `data/`：整併快取（`all_bars.parquet` 小台 1 分 K、`all_taiex_bars.parquet`、
  `all_tsmc_morning.parquet`、`us_sox*.parquet`…），**進 git**（重跑研究不必重抓）。
- `docs/`：`HANDOFF-AUDIT.md`（給外部 AI 審核的交接文件，開頭即「請優先攻擊的弱點」）、
  `FIVEYEAR-VALIDATION-CHATGPT.md`（外部五年 tick 驗證）。
- `.github/`：`workflows/walkforward.yml` **是本 repo 唯一的資料 workflow**（另有本次新增的
  `workflows/canon.yml` 守 CANON 區塊）；`actions/notify-failure/action.yml` 與
  `claude-harness/templates/notify-failure/action.yml` **逐字相同**（2026-09-07 `diff` 空）。

## 排程（改前先讀 `walkforward.yml` 頂端註解）

`.github/workflows/walkforward.yml` 兩班 cron（POSIX dow，`1-5`＝週一~五）：

| cron 原文 | UTC | 台北 | 角色 |
|-----------|-----|------|------|
| `7 13 * * 1-5` | 13:07 一~五 | 21:07 | 主班 |
| `7 15 * * 1-5` | 15:07 一~五 | 23:07 | 兜底（tick 未落地時補） |

- **兩班都刻意排在台北午夜前**：GitHub cron 常態延遲 1~2 小時，排 22:37 那類時間會跨午夜把目標日
  滾成隔天（taiwan-stock-news 2026-07-16 的實際事故）。理由原樣寫在該檔頂端註解。
- **目標日口徑**：`walkforward_daily.py` 的 `target = (now - dt.timedelta(hours=12)).date()`
  ——台北 `hour<12` 回推一天，與 `taiwan-flows` 的 `target_trading_day()` 同一套。
  `if target.weekday() >= 5` 週末跳過；**冪等**（同日已在 `ledger.csv` 即 return）；
  tick／SOX 未落地 → 正常結束（exit 0），由下一班或隔日補。
- **無 Worker 主觸發**：家族其他管線多由 taiwan-flow-live-v2 的 Worker 哨兵 dispatch，本 repo
  兩班都是 GH cron 自跑（`docs/schedule-map.md` 的 taiwan-backtest 節即此二條）。
- **失敗告警**：job 末步 `uses: ./.github/actions/notify-failure`＋`if: failure() || cancelled()`，
  `pipeline: v2-walkforward`；workflow 頂層 `permissions` 含 `issues: write`。

## 頂列「資料日｜狀態」（判準在 `function ledgerStatus`）

判準與門檻的完整推導寫在 `index.html` 中 `function ledgerStatus` 上方的區塊註解（「帳冊新鮮度」段），
**改門檻前先讀那段**。語意比照 taiwan-flows `siteStatus()`／postmkt 的頂列，但門檻依本站排程重算：

- 先把台北時鐘**回推 12 小時**得「參考班次日」`refDay`（與 `walkforward_daily.py` 的 target 同一套）。
- 參考時鐘上：`< 09:07`（台北 21:07 前）＝**正常**（今日班次尚未排定）；`09:07~13:07`
  （台北 21:07 ~ 隔日 01:07）＝**等待資料發布**（主班＋兜底＋自述 1~2 小時延遲的窗內）；
  `>= 13:07` 仍缺＝**資料缺漏**（13:07 ＝ 兜底 23:07 ＋ 延遲上限 2 小時）。
- `refDay` 為週末＝**休市定格**（帳冊 ≥ 上一個平日即可）；落後一個交易日以上一律**資料缺漏**。
- **CSV 讀不到或最後一列日期格式不合＝「查詢失敗（未知）」，用中性灰 `st-mut` 不用紅**
  ——「未知」是不知道資料好壞，**不是**資料異常。這是家族共通約定（入口站 `showStatusFail()`、
  taiwan-flows `siteStatus()` 同語意），**不可為了畫面好看改成綠色或靜默**。
- 前端 `renderTopline` 由載入流程呼叫；`fetch` 失敗時**明確** `renderTopline("")`，不得靜默當正常。
- 外部監看：`claude-harness/tools/freshness_watchdog.py` 的 `backtest` 站以 raw main 的
  `walkforward/ledger.csv` **檔尾**（Range）最後一列日期做同一套判定（2026-09-07 納入）。

## 首屏證據排序（2026-09-07 使用者裁決，改版面前必讀）

**先看到「這個答案能信到什麼程度」，再看到答案**——`id="sec-credibility"` 的降級結論
**必須留在績效數字（`.statwrap` 那組卡）之上**，`index.html` 該處註解記載 390x844 首屏內
以 `getBoundingClientRect` 實測兩者同時可見。`id="sec-audit"` 是同一條線的下游：降級卡一句話
點出結論並錨連到它，稽核卡才展開四點細節（引擎重現一致／證據強度排序／外部五年驗證／影子帳冊）。
**改版時不得把績效卡搬到降級卡之前，也不得把降級敘述折疊起來。**

## 誠實原則（本站鐵律，不可淡化）

1. 站上 2026-09-05 稽核卡的**降級結論**、`README.md` 頂部導讀表、以及原文各段的
   **9 處原地加註（🔻）**（2026-09-07 `grep -c "🔻" README.md` 實測）**都是刻意保留的**：
   原文數字一律不刪、與降級結論並陳讓讀者自行比對。**不可為了「看起來好看」而移除、合併或淡化**。
2. 「歷史段 18/18」「現代段 4/4」等字樣出現時**必須連同降級語一起出現**；空方桶證據強度較高、
   做多桶降級為僅現代段樣本——這個區分不可抹平。
3. 前推帳冊是**模擬**（`pnl_sim`）、未含滑價，「觸價即成交」是理想化假設；乾淨前推樣本
   **自 2026-09-07 起算**（凍結首日非嚴格事前）。頁面固定免責卡與 footer「僅供研究」不可拿掉。
4. 規則凍結：`walkforward_daily.py` 的 v3-SL 規則與已落帳的列**不回頭改**；要改＝關舊帳冊、
   開新編號帳冊重來（`SHADOW-SPEC.md` 同一原則）。

## 已知未做／限制（現況，不是待辦清單）

- `index.html` 仍留著 `<meta http-equiv="Cache-Control" ...>`——taiwan-flow-live-v2 已於 2026-09-06
  判定這類 meta 對現代瀏覽器無效並移除（見該 repo CLAUDE.md「CSP 與注入面」段），本站尚未跟進。
- **本站沒有 CSP meta**（家族另四站 index.html 都有 `<meta http-equiv="Content-Security-Policy">`）。
  現況注入面很小（唯一 fetch 是同源自家 CSV、動態值全過 `esc()`、無外連 script），但這是「還沒做」，
  不是「不需要」。
- `walkforward_daily.py` **只擋週末、不擋國定假日**（repo 無行事曆來源，與家族另四站同立場）：
  假日當晚頂列可能誤報一次「資料缺漏」，反向誤差是空手桶的假日仍可能記一列。兩者皆為已知可接受。
- 測試**不是 pytest 套件、也沒有任何 CI 在跑**：`walkforward/test_shadow.py` 與 `audit/tests_audit.py`
  是兩支獨立可執行的離線腳本（免 token 免網路），要靠人手動跑。

## 驗證方式

```bash
python3 walkforward/test_shadow.py   # 影子出場模擬離線單元測試（免 token 免網路）
python3 audit/tests_audit.py         # 稽核引擎回歸測試（免 token 免網路；pytest 亦可）
python3 -m http.server 8000          # 前端本機驗證：三區塊渲染、頂列狀態、console 零 error
```

改前端後至少驗：①降級卡仍在績效卡之上（390x844 首屏兩者同時可見）②頂列五種狀態語意未變
③`ledger.csv` 讀不到時顯示「查詢失敗（未知）」而非靜默正常。
改排程或 `ledgerStatus` 門檻時，**同步更新 `claude-harness/docs/schedule-map.md` 與
`tools/freshness_watchdog.py` 的 backtest 判準**（三處共用同一套口徑）。
