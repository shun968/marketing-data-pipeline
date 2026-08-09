#!/usr/bin/env bash
set -euo pipefail

# maritime-collector 用のcronラッパー(ADR-0008)。
#
# sns-collector/scripts/cron_run.sh と同型だが、全呼び出しに
# --data-dir/--keywords/--db/--reports-dir を明示し、sns-collector本体の
# data/state/reports には一切触れない。
#
# cwdを sns-collector/ へ移さない理由:
#   `uv run --project <sns-collector> ...` で依存解決だけをsns-collector側に
#   委ね、実行時のcwdはこのディレクトリ(maritime-collector/)に留める。
#   cwdをsns-collector/へ移すと、python-dotenvが実行時cwdから.envを探すため、
#   将来 maritime-collector/.env を置いてもそちらが見つからず、
#   sns-collector/.env が誤って使われてしまう。
#
# コマンドごとに受け取れるフラグの部分集合が違う(sns-collector/src/sns_collector/cli.py
# を参照。収集コマンドは --keywords/--data-dir/--db、report は --reports-dir/--data-dir/--db)。
# コマンド別に関数を割ると、コマンドを増やすたびに「呼び出し側」と「関数定義」の
# 2箇所を保守することになるため、1つのcaseでフラグ配列を組み立てる形にする。
#
# extract/embed/graph rebuild はここに含めない。抽出はClaude Codeセッションを
# 要する手動運用のため(sns-collector/README.md「これらはcronに登録しない」と同じ理由)。

COMMAND="${1:?usage: cron_run.sh <bluesky|hackernews|report>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOPIC_DIR="$(cd "${HERE}/.." && pwd)"
SNS_COLLECTOR_DIR="$(cd "${TOPIC_DIR}/../sns-collector" && pwd)"

DATA_DIR="${TOPIC_DIR}/data"
DB="${DATA_DIR}/analysis.duckdb"

LOCK_FILE="${TOPIC_DIR}/state/.locks/collector.lock"
LOG_FILE="${TOPIC_DIR}/state/.logs/${COMMAND}.log"
mkdir -p "$(dirname "${LOCK_FILE}")" "$(dirname "${LOG_FILE}")"

exec 200>"${LOCK_FILE}"
flock -n 200 || { echo "[$(date -Is)] skip: another maritime-collector run is in progress" >> "${LOG_FILE}"; exit 0; }

args=()
case "${COMMAND}" in
  bluesky|hackernews)
    args=(--keywords "${TOPIC_DIR}/config/keywords.yaml" --data-dir "${DATA_DIR}" --db "${DB}")
    ;;
  report)
    args=(--reports-dir "${TOPIC_DIR}/reports" --data-dir "${DATA_DIR}" --db "${DB}")
    ;;
  *)
    echo "未対応のコマンド: ${COMMAND}" >&2
    exit 2
    ;;
esac

{
  echo "[$(date -Is)] start: ${COMMAND}"
  ( cd "${TOPIC_DIR}" && uv run --project "${SNS_COLLECTOR_DIR}" sns-collector "${COMMAND}" "${args[@]}" )
  echo "[$(date -Is)] done: ${COMMAND}"
} >> "${LOG_FILE}" 2>&1
