#!/usr/bin/env bash
# tools/aisc_cron.sh — AI 供應鏈每日描述表（Phase 0）的 Hetzner cron 入口。
#
# 做什麼：（每月 11 號起第一班）台股候選池依 postmkt screen.json 換池 → 抓候選池最新還原價 → 算 ext／r5／MA60／R2 → 寫 output/aisc/daily/<date>.{csv,md} → 推 LINE
#         → commit／push output/aisc/daily（換池時連同 aisc/universe.json）。純描述、不產委託單、不送單。
# 用法：bash tools/aisc_cron.sh [--dry-run] [--no-push-line]   （--dry-run：不換池、不推 LINE、不 commit，結束時還原工作樹）
#   REPO_DIR  repo 位置（預設 /root/projects/taiwan-backtest）
#   ENV_FILE  只含 FINMIND_TOKEN=／LINE_TOKEN=／LINE_USER_ID= 的環境檔，須存在且權限 0600（否則 exit 3）
# 建議排程（台北）：台股收盤後 15:30 跑一次（美股前一夜資料 FinMind 多在台北早上入庫，同一班就能帶到）；
#   crontab 範例：30 7 * * 1-5 bash /root/projects/taiwan-backtest/tools/aisc_cron.sh >> /var/log/aisc.log 2>&1
#   （機器若為 UTC，07:30 UTC＝台北 15:30）
# 全程不 echo 任何環境變數值。
set -euo pipefail
REPO_DIR="${REPO_DIR:-/root/projects/taiwan-backtest}"
ENV_FILE="${ENV_FILE:-/root/.config/aisc.env}"
DRY_RUN=0; PUSH="--push"
# 自我更新：記下啟動時的腳本內容；pull 後若本檔變了就以新版重跑一次（bash 會繼續讀已開啟的舊檔，
# 不重跑的話「改了本腳本」的那一班跑的是舊流程——2026-10-14 那班即是如此）
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
SELF_SHA="$(sha256sum "$SELF" | cut -d' ' -f1)"
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-push-line) PUSH="" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
# dry-run 一律不推 LINE
[ "$DRY_RUN" = "1" ] && PUSH=""
log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
[ -f "$ENV_FILE" ] || { log "ENV_FILE 不存在：$ENV_FILE（exit 3）"; exit 3; }
[ "$(stat -c '%a' "$ENV_FILE")" = "600" ] || { log "ENV_FILE 權限須為 600（exit 3）"; exit 3; }
cd "$REPO_DIR"
if [ -n "$(git status --porcelain)" ]; then log "工作樹不乾淨，拒跑（exit 4）"; git status --short; exit 4; fi
git fetch origin main && git checkout -q main && git pull --ff-only origin main || { log "pull 失敗（exit 4）"; exit 4; }
if [ -z "${AISC_CRON_REEXEC:-}" ] && [ "$(sha256sum "$SELF" | cut -d' ' -f1)" != "$SELF_SHA" ]; then
  log "腳本已隨 pull 更新，以新版重跑一次"
  exec env AISC_CRON_REEXEC=1 bash "$SELF" "$@"
fi
set -a; . "$ENV_FILE"; set +a
# Python：repo 內有 .venv（Hetzner 系統 Python 受 PEP 668 管理、套件裝在 venv）就用它，否則退回系統 python3
PY="python3"; [ -x .venv/bin/python ] && PY=".venv/bin/python"
rc=0
# 候選池換池在每日表之前（到期才動 aisc/universe.json）；失敗不擋每日表，但最後的退出碼會反映
ref_rc=0
REF_ARGS=""; [ "$DRY_RUN" = "1" ] && REF_ARGS="--dry-run"
"$PY" -m aisc.universe_refresh $REF_ARGS || ref_rc=$?
log "universe_refresh exit=$ref_rc"
"$PY" -m aisc.daily_table $PUSH || rc=$?
log "daily_table exit=$rc"
[ "$rc" = "0" ] && rc="$ref_rc"
git add output/aisc/daily aisc/universe.json
if [ "$DRY_RUN" = "1" ]; then
  # 列出本來會 commit 的檔，再把改動與新產生的檔全部還原，否則下一班會因工作樹不乾淨 exit 4
  git diff --cached --name-only
  git reset -q -- output/aisc/daily aisc/universe.json
  git checkout -q -- output/aisc/daily aisc/universe.json
  git clean -fdq -- output/aisc/daily
  exit "$rc"
fi
if git diff --cached --quiet; then log "無變化"; exit "$rc"; fi
git config user.name >/dev/null 2>&1 || git config user.name "hetzner-cron"
git config user.email >/dev/null 2>&1 || git config user.email "hetzner-cron@localhost"
# commit 訊息帶「本次寫入的檔名日期」＋「台北執行日」，兩者常不同（台股還原價晚一天落地），不可只寫執行日
FILE_DATES="$(git diff --cached --name-only -- output/aisc/daily | sed -n 's#.*/\([0-9-]\{10\}\)\.\(csv\|md\)$#\1#p' | sort -u | paste -sd, -)"
POOL=""; git diff --cached --quiet -- aisc/universe.json || POOL=" + 候選池換池"
git commit -q -m "aisc daily table ${FILE_DATES:-?}${POOL} (run $(TZ=Asia/Taipei date +%F), hetzner)"
for i in 1 2 3 4 5; do
  if git pull --rebase origin main && git push origin HEAD:main; then log "已 push"; exit "$rc"; fi
  git rebase --abort 2>/dev/null || true; sleep 4
done
log "push failed after 5 retries"; exit 1
