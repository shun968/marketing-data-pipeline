#!/usr/bin/env bash
set -euo pipefail

# maritime-collector 用のcronラッパー(ADR-0008)。
#
# sns-collector/scripts/cron_run.sh と同型だが、全呼び出しに
# --data-dir/--keywords/--db/--reports-dir を明示し、sns-collector本体の
# data/state/reports には一切触れない。
#
# ロック・ログまわりの実装(25-38行目)がsns-collector/scripts/cron_run.shと
# ほぼ重複しているのは意図的である。共有ヘルパーへ切り出すと、2つのトピック
# ディレクトリから相対パスで正しく解決させる分岐が増え、この単純なロック取得
# 自体より複雑になる。ADR-0008がコード複製を避けたのはPythonパッケージ側の
# 話であり、この15行程度のシェル定型句には同じ判断を適用していない。
#
# cwdを sns-collector/ へ移さない理由:
#   `uv run --directory <topic> --project <sns-collector> ...` で依存解決は
#   sns-collector側に委ね、実行時のcwdは`--directory`で明示的にこのディレクトリ
#   (maritime-collector/)へ留める。相対パスの解決先をトピック側に揃えるため。
#
# APIキーについて:
#   このトピックはbluesky/hackernewsのみで鍵が要らないため、
#   SNS_COLLECTOR_ENV_FILE を設定していない。鍵を要する収集元を足すときは、
#   ワークスペース外のパスを指してこの変数をexportする(ADR-0012)。
#   **トピックディレクトリ配下に .env を置かない。** cwdからの暗黙探索は
#   config_file.py で塞いであるが、ファイルを置けばセッションの子プロセスから
#   読める状態そのものは戻る(docs/isolation.md §3 経路3)。
#
# bash -lc を挟む理由:
#   cronは最小限のPATHしか持たない。sns-collector/README.md「定期実行(cron)」の
#   注記の通り、この環境ではsnapサンドボックスの影響でuvが
#   $HOME/snap/code/.../binのような特殊なパスに配置されており、非ログインシェル
#   ではPATHが通らない。sns-collector/scripts/cron_run.shと同じ対策が要る。
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
  bash -lc "uv run --directory '${TOPIC_DIR}' --project '${SNS_COLLECTOR_DIR}' sns-collector '${COMMAND}' ${args[*]@Q}"
  echo "[$(date -Is)] done: ${COMMAND}"
} >> "${LOG_FILE}" 2>&1
