#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:?usage: cron_run.sh <bluesky|youtube>}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${PROJECT_DIR}/state/.locks/${PLATFORM}.lock"
LOG_FILE="${PROJECT_DIR}/state/.logs/${PLATFORM}.log"
mkdir -p "$(dirname "${LOCK_FILE}")" "$(dirname "${LOG_FILE}")"

exec 200>"${LOCK_FILE}"
flock -n 200 || { echo "[$(date -Is)] skip: previous run still in progress" >> "${LOG_FILE}"; exit 0; }

{
  echo "[$(date -Is)] start: ${PLATFORM}"
  bash -lc "cd '${PROJECT_DIR}' && uv run sns-collector ${PLATFORM}"
  echo "[$(date -Is)] done: ${PLATFORM}"
} >> "${LOG_FILE}" 2>&1
