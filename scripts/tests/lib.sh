#!/usr/bin/env bash
# 回帰テストの共通処理。各 *.test.sh から source して使う。
#
# なぜ切り出すか:
#   同じ setup / teardown / 集計が6ファイルへ書き写されており、
#   ヘルパを直すたびに全ファイルを追う必要があった。
#   テスト作法を変えるときの変更点を1箇所にする。
#
# 使い方:
#   source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#   suite_begin "対象スクリプト名"
#   ...
#   suite_end

passed=0
failed=0
workdir=""

# suite_begin <見出し>
suite_begin() {
  echo "$1"
}

# 使い捨ての作業ディレクトリを作って移動する
new_workdir() {
  workdir="$(mktemp -d)"
  # 移動できないまま続けると、テストがリポジトリ本体を書き換える
  cd "${workdir}" || exit 1
}

# new_workdir に加えて空のgitリポジトリを用意する
new_git_workdir() {
  new_workdir
  git init -q .
  git config user.email test@example.com
  git config user.name test
}

cleanup_workdir() {
  cd /
  [ -n "${workdir}" ] && rm -rf "${workdir}"
  workdir=""
}

# pass <ケース名>
pass() {
  echo "  ok   $1"
  passed=$((passed + 1))
}

# fail <ケース名> <期待> <実際>
fail() {
  echo "  FAIL $1（期待: $2 / 実際: $3）"
  failed=$((failed + 1))
}

# check_exit <期待する終了コード> <ケース名> <実際の終了コード>
check_exit() {
  if [ "$3" -eq "$1" ]; then
    pass "$2"
  else
    fail "$2" "$1" "$3"
  fi
}

# assert_eq <期待> <実際> <ケース名>
# `[ ... ] && pass || fail` と書くと、pass の終了コード次第で fail も走る
assert_eq() {
  if [ "$1" = "$2" ]; then
    pass "$3"
  else
    fail "$3" "$1" "$2"
  fi
}

# assert_cmd_exit <期待する終了コード> <ケース名> <コマンド...>
# 各テストの assert_exit はこれを包むだけにする。
# 同じ引数説明を6ファイルへ書き写さないため
assert_cmd_exit() {
  local expected="$1" name="$2"
  shift 2
  local actual=0
  "$@" > /dev/null 2>&1 || actual=$?
  check_exit "${expected}" "${name}" "${actual}"
}

# 集計を出力し、失敗があれば非0で終わる
suite_end() {
  echo "  ---"
  echo "  成功 ${passed} / 失敗 ${failed}"
  [ "${failed}" -eq 0 ]
}
