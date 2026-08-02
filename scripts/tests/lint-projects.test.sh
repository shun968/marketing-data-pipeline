#!/usr/bin/env bash
set -euo pipefail

# scripts/lint-projects.sh の回帰テスト。
#
# このスクリプトの怖い壊れ方は「lintが落ちること」ではなく
# **「対象を1つも選ばずに成功すること」**である。
# staged判定が壊れると、lintを通していないコミットが緑のまま通る。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/lint-projects.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ORIGINAL_PATH="${PATH}"

setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
  git init -q .
  git config user.email test@example.com
  git config user.name test
  mkdir -p scripts bin
  cp "${SCRIPT}" scripts/lint-projects.sh

  # npm をスタブ化する。
  # 本物を使うと、この回帰テストを回すpre-commitとCIの guards ジョブが
  # Node の導入状況に依存する(guards は uv しか用意していない)。
  # 実行時間も1ケースあたり300ms程度かかる。
  # package.json の lint スクリプトを直接実行すれば、検証したい
  # 「どのディレクトリを対象に選ぶか」の挙動は変わらない
  cat > bin/npm <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "run" ] || exit 0
script="$(sed -n 's/.*"lint"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' package.json)"
[ -n "${script}" ] || exit 1
eval "${script}"
STUB
  chmod +x bin/npm
  PATH="${workdir}/bin:${PATH}"
  export PATH
}

teardown() {
  cd /
  PATH="${ORIGINAL_PATH}"
  export PATH
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

assert_exit() {
  assert_cmd_exit "$1" "$2" ./scripts/lint-projects.sh "${@:3}"
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

suite_end
