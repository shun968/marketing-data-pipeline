#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:?usage: cron_run.sh <bluesky|youtube|hackernews>}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ロックはプラットフォーム別ではなく共有にする。
#   収集は data/analysis.duckdb を書き込みで開く（ADR-0004）。DuckDBは
#   プロセス間で排他ロックを取るため、bluesky(0 */3)・youtube(15 */3)・
#   hackernews(30 */3) が重なると後発がHTTP通信の前に IOException で落ちる。
#   プラットフォーム別ロックでは、その衝突を防げない。
LOCK_FILE="${PROJECT_DIR}/state/.locks/collector.lock"
LOG_FILE="${PROJECT_DIR}/state/.logs/${PLATFORM}.log"
mkdir -p "$(dirname "${LOCK_FILE}")" "$(dirname "${LOG_FILE}")"

exec 200>"${LOCK_FILE}"
flock -n 200 || { echo "[$(date -Is)] skip: another collector run is in progress" >> "${LOG_FILE}"; exit 0; }

{
  echo "[$(date -Is)] start: ${PLATFORM}"
  bash -lc "cd '${PROJECT_DIR}' && uv run sns-collector ${PLATFORM}"
  echo "[$(date -Is)] done: ${PLATFORM}"
} >> "${LOG_FILE}" 2>&1
