#!/usr/bin/env bash
set -euo pipefail

# scripts/record-check.sh の回帰テスト。
#
# ここで最も重いのは「記録がゲートの挙動を変えないこと」である。
# 終了コードを1つ取りこぼすだけで、全ガードレールが静かに無効化される。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/record-check.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# このテスト自身が pre-commit から呼ばれる。gitがフックへ渡す GIT_INDEX_FILE が
# 残っていると、記録先の文脈判定も、テスト内で作る使い捨てリポジトリの
# git操作も、呼び出し元のリポジトリに引きずられる
unset GIT_INDEX_FILE

LOG=""

setup() {
  new_git_workdir
  LOG="${workdir}/events.jsonl"
}

teardown() {
  cleanup_workdir
  LOG=""
}

# run_recorder <検査名> <コマンド...> → 終了コードを actual へ
run_recorder() {
  local name="$1"
  shift
  local actual=0
  GUARDRAIL_LOG="${LOG}" GUARDRAIL_CONTEXT=test \
    "${SCRIPT}" "${name}" -- "$@" > /dev/null 2>&1 || actual=$?
  echo "${actual}"
}

# jq は前提にしない。記録はJSONLなのでPythonで読む
# field <キー> → 最終行の値
field() {
  python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    last = [line for line in f if line.strip()][-1]
print(json.loads(last)[sys.argv[2]])
' "${LOG}" "$1"
}

echo "record-check.sh"

# --- 終了コードの素通し（最重要） ---

setup
check_exit 0 "成功した検査の終了コードを返す" "$(run_recorder ok true)"
teardown

setup
check_exit 1 "失敗した検査の終了コードを返す" "$(run_recorder ng false)"
teardown

# 終了コードを 0/1 へ丸めると、usage違反(2)と違反検出(1)が区別できなくなる
setup
check_exit 2 "0/1以外の終了コードもそのまま返す" "$(run_recorder usage bash -c 'exit 2')"
teardown

# 記録できない状況でも検査は通常どおり終わる。
# 観測のためにゲートが止まるのは本末転倒
setup
actual=0
GUARDRAIL_LOG=/proc/nonexistent/events.jsonl GUARDRAIL_CONTEXT=test \
  "${SCRIPT}" ok -- true > /dev/null 2>&1 || actual=$?
check_exit 0 "記録に失敗しても検査の結果を変えない" "${actual}"
teardown

# --- 記録の内容 ---

setup
run_recorder ok true > /dev/null
check_exit 0 "成功時も記録する（発火していないルールを見つけるため）" "$([ -s "${LOG}" ] && echo 0 || echo 1)"
teardown

setup
run_recorder mycheck true > /dev/null
assert_eq "mycheck" "$(field check)" "検査名を記録する"
assert_eq "test" "$(field context)" "文脈を記録する"
assert_eq "0" "$(field exit_code)" "終了コードを記録する"
teardown

# 手元の作業回数とCIの実行回数を混ぜると「人が何回止められたか」が読めない
setup
GUARDRAIL_LOG="${LOG}" GIT_INDEX_FILE=/tmp/index "${SCRIPT}" x -- true > /dev/null 2>&1
assert_eq "git-hook" "$(field context)" "gitフック経由と手動実行を区別する"
teardown

setup
GUARDRAIL_LOG="${LOG}" "${SCRIPT}" x -- true > /dev/null 2>&1
assert_eq "manual" "$(field context)" "手動実行はmanualとして記録する"
teardown

# ルールIDが集計の単位になる。ここが取れないとメトリクスが成立しない
setup
run_recorder guard bash -c 'echo "NG: [private-file] sns-collector/data/x.jsonl" >&2; exit 1' > /dev/null
assert_eq "1" "$(field violations)" "違反件数を記録する"
assert_eq "['private-file']" "$(field rules)" "ルールIDを記録する"
teardown

setup
run_recorder guard bash -c 'echo "NG: [a] x" >&2; echo "NG: [b] y" >&2; echo "NG: [a] z" >&2; exit 1' > /dev/null
assert_eq "3" "$(field violations)" "同じルールの複数回発火を数える"
teardown

# **記録に違反の中身を残さない。** 秘匿情報の検査は
# 「どのファイルの何行目に鍵があるか」を出力するため、
# そのまま記録すると鍵の在り処がログに溜まる
setup
run_recorder secrets bash -c 'echo "NG: [secret-string] Anthropic APIキーらしき文字列: config/prod.env:42" >&2; exit 1' > /dev/null
if grep -q 'prod.env' "${LOG}"; then
  fail "違反の詳細(ファイル名・行番号)を記録しない" "含まれない" "含まれている"
else
  pass "違反の詳細(ファイル名・行番号)を記録しない"
fi
teardown

# NG行が無ければ違反ゼロ。lint系は自前の書式で出すため、この経路を通る
setup
run_recorder lint bash -c 'echo "SC2086: ..." >&2; exit 1' > /dev/null
assert_eq "0" "$(field violations)" "NG行の無い失敗は違反0件として記録する"
assert_eq "1" "$(field exit_code)" "NG行が無くても終了コードは残る"
teardown

# 追記であること。上書きすると推移が取れない
setup
run_recorder a true > /dev/null
run_recorder b true > /dev/null
lines="$(wc -l < "${LOG}")"
assert_eq "2" "${lines}" "1実行につき1行を追記する"
teardown

# --- 出力の素通し ---

# 検査のメッセージが消えると、何が悪いのか分からないままコミットが止まる
setup
out="$(GUARDRAIL_LOG="${LOG}" "${SCRIPT}" x -- bash -c 'echo "NG: [r] 詳細" >&2' 2>&1 || true)"
case "${out}" in
  *"NG: [r] 詳細"*) pass "検査の標準エラーをそのまま流す" ;;
  *) fail "検査の標準エラーをそのまま流す" "NG行を含む" "${out}" ;;
esac
teardown

setup
out="$(GUARDRAIL_LOG="${LOG}" "${SCRIPT}" x -- bash -c 'echo "進捗"' 2>/dev/null || true)"
case "${out}" in
  *進捗*) pass "検査の標準出力をそのまま流す" ;;
  *) fail "検査の標準出力をそのまま流す" "進捗を含む" "${out}" ;;
esac
teardown

# --- 引数 ---

setup
check_exit 2 "検査名が無ければ使い方を示して終了する" "$(GUARDRAIL_LOG="${LOG}" "${SCRIPT}" > /dev/null 2>&1; echo $?)"
teardown

setup
check_exit 2 "-- 区切りが無ければ拒否する" "$(GUARDRAIL_LOG="${LOG}" "${SCRIPT}" name true > /dev/null 2>&1; echo $?)"
teardown

setup
check_exit 2 "コマンドが無ければ拒否する" "$(GUARDRAIL_LOG="${LOG}" "${SCRIPT}" name -- > /dev/null 2>&1; echo $?)"
teardown

suite_end
