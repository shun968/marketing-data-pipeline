#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:?usage: cron_run.sh <bluesky|youtube|hackernews|report>}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ロックはコマンド別ではなく共有にする。
#   収集・report はいずれも data/analysis.duckdb を書き込みで開く（ADR-0004）。
#   DuckDBはプロセス間で排他ロックを取るため、bluesky(0 */3)・youtube(15 */3)・
#   hackernews(30 */3)・report(週次)が重なると後発が IOException で落ちる。
#   コマンド別ロックでは、その衝突を防げない。
# APIキーの置き場。**ホストのホーム配下を指す**（ADR-0012）。
# このラッパーが走るのはホストのcronであり、${HOME}はホスト側のホームになる。
# devcontainer内のホームは再作成で消えるうえ、ここからは見えない。
# ここを PROJECT_DIR 配下へ戻すと、devcontainer内のセッションの子プロセスから
# 鍵が読める状態に戻る（docs/isolation.md §3 経路3）。
# 指定先が無い場合、キーを要する収集は ConfigError で止まる（黙って
# トークン無しの劣化状態で走らせない）。
export SNS_COLLECTOR_ENV_FILE="${SNS_COLLECTOR_ENV_FILE:-${XDG_CONFIG_HOME:-${HOME}/.config}/sns-collector/.env}"

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
