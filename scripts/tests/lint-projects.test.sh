#!/usr/bin/env bash
set -euo pipefail

# scripts/lint-projects.sh の回帰テスト。
#
# このスクリプトの怖い壊れ方は「lintが落ちること」ではなく
# **「対象を1つも選ばずに成功すること」**である。
# staged判定が壊れると、lintを通していないコミットが緑のまま通る。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/lint-projects.sh"

passed=0
failed=0
workdir=""

setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
  git init -q .
  git config user.email test@example.com
  git config user.name test
  mkdir -p scripts
  cp "${SCRIPT}" scripts/lint-projects.sh
}

teardown() {
  cd /
  [ -n "${workdir}" ] && rm -rf "${workdir}"
}

# make_project <ディレクトリ> <lintスクリプト|->
make_project() {
  mkdir -p "$1"
  if [ "$2" = "-" ]; then
    printf '{ "name": "%s", "scripts": { "build": "true" } }\n' "$1" > "$1/package.json"
  else
    printf '{ "name": "%s", "scripts": { "lint": "%s" } }\n' "$1" "$2" > "$1/package.json"
  fi
}

# assert_linted <期待するディレクトリ数> <ケース名> [引数...]
# 「対象を選ばずに成功する」壊れ方を捕まえるため、実行件数を数える
assert_linted() {
  local expected="$1" name="$2" actual
  shift 2
  actual="$(./scripts/lint-projects.sh "$@" 2>/dev/null | grep -c '^==> lint:' || true)"
  if [ "${actual}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected}件 / 実際: ${actual}件）"
    failed=$((failed + 1))
  fi
}

# assert_exit <期待する終了コード> <ケース名> [引数...]
assert_exit() {
  local expected="$1" name="$2" actual=0
  shift 2
  ./scripts/lint-projects.sh "$@" > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected} / 実際: ${actual}）"
    failed=$((failed + 1))
  fi
}

echo "lint-projects.sh"

setup
make_project proj true
assert_linted 1 "lintスクリプトを持つディレクトリを対象にする"
teardown

setup
make_project proj -
assert_linted 0 "lintスクリプトを持たないディレクトリは対象外"
teardown

setup
make_project proj false
assert_exit 1 "lintが失敗したら非0で終わる"
teardown

# --- --staged-only ---

setup
make_project proj true
git add -A
assert_linted 1 "--staged-only: stagedに含まれるプロジェクトを対象にする" --staged-only
teardown

setup
make_project proj true
make_project other true
git add other
assert_linted 1 "--staged-only: stagedに含まれないプロジェクトは対象外" --staged-only
teardown

setup
make_project proj true
assert_linted 0 "--staged-only: stagedが空なら何もしない" --staged-only
teardown

# -z が無いと非ASCIIパスは "\346..." へクォートされ、ディレクトリ判定に失敗して
# そのプロジェクトのlintが黙ってスキップされる
setup
make_project proj true
git add -A
git commit -qm init
echo 'メモ' > "proj/日本語ファイル.md"
git add "proj/日本語ファイル.md"
assert_linted 1 "--staged-only: 日本語ファイル名でもプロジェクトを判定できる" --staged-only
teardown

echo "  ---"
echo "  成功 ${passed} / 失敗 ${failed}"
[ "${failed}" -eq 0 ]
