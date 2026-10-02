#!/usr/bin/env bash
# tools/aisc_cron.sh — AI 供應鏈每日描述表（Phase 0）的 Hetzner cron 入口。
#
# 做什麼：抓 117 檔最新還原價 → 算 ext／r5／MA60／R2 → 寫 output/aisc/daily/<date>.{csv,md} → 推 LINE
#         → commit／push output/aisc/daily。純描述、不產委託單、不送單。
# 用法：bash tools/aisc_cron.sh [--dry-run] [--no-push-line]
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
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-push-line) PUSH="" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
[ -f "$ENV_FILE" ] || { log "ENV_FILE 不存在：$ENV_FILE（exit 3）"; exit 3; }
[ "$(stat -c '%a' "$ENV_FILE")" = "600" ] || { log "ENV_FILE 權限須為 600（exit 3）"; exit 3; }
cd "$REPO_DIR"
if [ -n "$(git status --porcelain)" ]; then log "工作樹不乾淨，拒跑（exit 4）"; git status --short; exit 4; fi
git fetch origin main && git checkout -q main && git pull --ff-only origin main || { log "pull 失敗（exit 4）"; exit 4; }
set -a; . "$ENV_FILE"; set +a
rc=0
python3 -m aisc.daily_table $PUSH || rc=$?
log "daily_table exit=$rc"
git add output/aisc/daily
if git diff --cached --quiet; then log "無變化"; exit "$rc"; fi
if [ "$DRY_RUN" = "1" ]; then git diff --cached --name-only; git reset -q -- output/aisc/daily; exit "$rc"; fi
git config user.name >/dev/null 2>&1 || git config user.name "hetzner-cron"
git config user.email >/dev/null 2>&1 || git config user.email "hetzner-cron@localhost"
git commit -q -m "aisc daily table $(TZ=Asia/Taipei date +%F) (hetzner)"
for i in 1 2 3 4 5; do
  if git pull --rebase origin main && git push origin HEAD:main; then log "已 push"; exit "$rc"; fi
  git rebase --abort 2>/dev/null || true; sleep 4
done
log "push failed after 5 retries"; exit 1
