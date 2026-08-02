#!/usr/bin/env bash
set -uo pipefail

# 検査スクリプトの実行を記録してから、その終了コードをそのまま返す。
#
# なぜ要るか:
#   どのガードレールが何回発火しているかが分からないと、規約の追加・削除・
#   機械化の判断が勘になる。一度も発火していないルールは剥がす候補であり、
#   繰り返し発火するルールは検査ではなく設計で潰す候補である。
#   その判断材料をモニタリング画面（dashboard/）へ渡すのがこの記録層の役目。
#
# 記録はゲートではない:
#   **記録に失敗しても検査の結果を変えない。** 観測のために本来のゲートが
#   止まるのは本末転倒で、記録側の不具合でコミットできなくなると
#   --no-verify の常用を招く。
#   同じ理由で、検査の終了コードは必ずそのまま返す。ここを握り潰すと
#   すべてのゲートが静かに無効化される。
#
# 使い方:
#   scripts/record-check.sh <検査名> -- <コマンド...>
#
# ルールIDの決め方（各検査スクリプトの report / check_rule はここを参照する）:
#   違反行は `NG: [<ルールID>] <詳細>` の形で出す。IDは集計の単位であり、
#   時系列で数えられることに意味がある。**詳細の文言を変えてもIDは変えない。**
#   IDを変えると同じルールが別物として集計され、推移が切れる。
#   形式は小文字の英数字とハイフンのみ（例: private-file / adr-headings）。
#   この形は scripts/check-repo-conventions.sh が機械的に検査する。
#
# 記録先:
#   .metrics/guardrail-events.jsonl（gitignore済み・1行1イベント）
#   GUARDRAIL_LOG で差し替えられる
#
# 対話的な検査は通さない:
#   標準エラーを一旦ファイルへ落とすため、端末とのやり取りを要する承認フロー
#   （scripts/check-rule-consolidation.sh）はラップしない。
#
# テスト: scripts/tests/record-check.test.sh

# set -e を付けない。検査が非0で終わってもここで中断せず、
# 記録してから終了コードを返す必要がある

NAME="${1-}"
if [ -z "${NAME}" ] || [ "${2-}" != "--" ]; then
  echo "usage: $0 <検査名> -- <コマンド...>" >&2
  exit 2
fi
shift 2

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <検査名> -- <コマンド...>" >&2
  exit 2
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
LOG_PATH="${GUARDRAIL_LOG:-${root:+${root}/}.metrics/guardrail-events.jsonl}"
CONTEXT="${GUARDRAIL_CONTEXT:-unknown}"

stderr_file="$(mktemp)"
trap 'rm -f "${stderr_file}"' EXIT

started_at="$(date --iso-8601=seconds)"
start_ns="$(date +%s%N)"

# 標準エラーを一旦ファイルへ落としてから流し直す。
# プロセス置換(`2> >(tee ...)`)にすると、tee の書き込み完了を待たずに
# 次の行へ進み、記録が空になったり途中で切れたりする。
# 標準出力は素通しなので、進捗表示はこれまでどおり流れる
exit_code=0
"$@" 2> "${stderr_file}" || exit_code=$?
cat "${stderr_file}" >&2

end_ns="$(date +%s%N)"
duration_ms=$(( (end_ns - start_ns) / 1000000 ))

# 記録が失敗しても検査の結果は変えない。
# 中で起きたことはすべて握り潰し、最後に exit_code を返す
record() {
  local dir
  dir="$(dirname "${LOG_PATH}")"
  mkdir -p "${dir}" 2>/dev/null || return 0

  # 違反ルールの抽出。検査スクリプトは違反を `NG: [<ルールID>] <詳細>` の形で
  # 標準エラーへ出す（scripts/check-repo-conventions.sh が強制する）。
  #
  # **ID だけを取り出し、詳細は捨てる。**
  # 詳細にはファイル名・行番号が入り、秘匿情報の検査では
  # 「どこに鍵があるか」を示す文字列になる。集計に要るのは
  # 「どのルールが何回発火したか」だけなので、記録もそこに限る。
  local rules=""
  if [ -s "${stderr_file}" ]; then
    rules="$(grep -ao '^NG: \[[a-z0-9-]*\]' "${stderr_file}" 2>/dev/null \
      | sed -e 's/^NG: \[//' -e 's/\]$//' || true)"
  fi

  CHECK_NAME="${NAME}" \
  CHECK_CONTEXT="${CONTEXT}" \
  CHECK_STARTED_AT="${started_at}" \
  CHECK_EXIT_CODE="${exit_code}" \
  CHECK_DURATION_MS="${duration_ms}" \
  CHECK_RULES="${rules}" \
  python3 -c '
import json, os, sys

rules = [line for line in os.environ.get("CHECK_RULES", "").splitlines() if line]

event = {
    "ts": os.environ["CHECK_STARTED_AT"],
    "check": os.environ["CHECK_NAME"],
    "context": os.environ["CHECK_CONTEXT"],
    "exit_code": int(os.environ["CHECK_EXIT_CODE"]),
    "duration_ms": int(os.environ["CHECK_DURATION_MS"]),
    "violations": len(rules),
    "rules": rules,
}
sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
' >> "${LOG_PATH}" 2>/dev/null || return 0
}

record || true

exit "${exit_code}"
