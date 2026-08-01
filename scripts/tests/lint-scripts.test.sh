#!/usr/bin/env bash
set -euo pipefail

# scripts/lint-scripts.sh の回帰テスト。
#
# ここで守りたいのは「指摘を検出できること」よりも、
# **検査したつもりで何も検査していない状態にならないこと**である。
# ファイル列挙が静かに0件になると、CIは緑のまま素通りする。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/lint-scripts.sh"
YAMLLINT_CONFIG="${REPO_ROOT}/.yamllint.yml"

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
  cp "${SCRIPT}" scripts/lint-scripts.sh
  # lint-scripts.sh から呼ばれるため、無いと 127 で落ちる
  cp "${REPO_ROOT}/scripts/check-shell-idioms.sh" scripts/
  cp "${YAMLLINT_CONFIG}" .yamllint.yml
}

teardown() {
  cd /
  [ -n "${workdir}" ] && rm -rf "${workdir}"
}

# assert_exit <期待する終了コード> <ケース名> [引数...]
assert_exit() {
  local expected="$1" name="$2" actual=0
  shift 2
  ./scripts/lint-scripts.sh "$@" > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected} / 実際: ${actual}）"
    failed=$((failed + 1))
  fi
}

# assert_fails <ケース名> [引数...]
# 終了コードの値そのものは問わない（gitの失敗はそのまま伝わるため128になる）
assert_fails() {
  local name="$1" actual=0
  shift
  ./scripts/lint-scripts.sh "$@" > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -ne 0 ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（成功してしまった）"
    failed=$((failed + 1))
  fi
}

# assert_scanned <期待ファイル数> <ケース名> [引数...]
# 「0件なのに成功する」状態を検出するため、検査した件数を確認する
assert_scanned() {
  local expected="$1" name="$2" actual
  shift 2
  actual="$(./scripts/lint-scripts.sh "$@" 2>/dev/null | grep -oP '^\s+\K[0-9]+(?= ファイル)' | head -1 || true)"
  if [ "${actual:-0}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected}ファイル / 実際: ${actual:-0}ファイル）"
    failed=$((failed + 1))
  fi
}

write_clean_sh() {
  {
    echo '#!/usr/bin/env bash'
    echo 'set -euo pipefail'
    echo 'echo "ok"'
  } > "$1"
}

echo "lint-scripts.sh"

# --- 正常系 ---

setup
write_clean_sh clean.sh
printf 'key: value\n' > config.yml
git add -A
assert_exit 0 "問題のないシェル・YAMLを通す"
teardown

# --- 検出すべきケース ---

setup
# 意図的にSC2086(未クォート展開)を含むフィクスチャを書き出す。
# 展開させたくないので単一引用符のままにする
# shellcheck disable=SC2016
{
  echo '#!/usr/bin/env bash'
  echo 'x=$1'
  echo 'echo $x'
} > bad.sh
git add -A
assert_exit 1 "shellcheckの指摘を検出する"
teardown

setup
printf 'a: [1, 2\n' > broken.yml
git add -A
assert_exit 1 "YAMLの構文エラーを検出する"
teardown

setup
printf 'a: 1\na: 2\n' > dup.yml
git add -A
assert_exit 1 "YAMLのキー重複を検出する"
teardown

# --- 「検査したつもり」を防ぐケース ---

# -z が無いと非ASCIIパスがCクォートされ、実在しないパスがlinterへ渡って
# 日本語名のファイルが1つあるだけで全コミット・全CIが落ちる
setup
write_clean_sh "検査対象.sh"
printf 'key: value\n' > "設定.yml"
git add -A
assert_exit 0 "日本語ファイル名でも落ちない"
teardown

setup
write_clean_sh "検査対象.sh"
git add -A
assert_scanned 3 "日本語ファイル名のファイルを検査対象に含む（検査スクリプト2本+1）"
teardown

# `git rm` ではなく `rm` で消したファイルはindexに残る。
# 実体の無いパスを渡すとlinterが中断し、無関係なコミットまで止まる
setup
write_clean_sh removed.sh
git add -A
git commit -qm init
rm removed.sh
assert_exit 0 "worktreeから消えたファイルがあっても中断しない" --all
teardown

# gitが失敗したときに「対象なし」で緑にならないこと。
# mapfile < <(git ...) だと配列が空になるだけで exit 0 してしまう
setup
outside="$(mktemp -d)"
mkdir -p "${outside}/scripts"
cp scripts/lint-scripts.sh "${outside}/scripts/"
cd "${outside}"
assert_fails "gitリポジトリ外では失敗する（0件で成功しない）"
cd /
rm -rf "${outside}"
teardown

# --- モード ---

setup
write_clean_sh staged.sh
git add staged.sh
write_clean_sh untracked.sh
assert_scanned 1 "--staged は未追跡ファイルを対象にしない" --staged
teardown

setup
write_clean_sh tracked.sh
git add -A
git commit -qm init
write_clean_sh untracked.sh
assert_scanned 3 "--all は未追跡ファイルを対象にしない" --all
teardown

setup
write_clean_sh tracked.sh
git add -A
git commit -qm init
write_clean_sh untracked.sh
assert_scanned 4 "既定は未追跡ファイルも対象にする"
teardown

echo "  ---"
echo "  成功 ${passed} / 失敗 ${failed}"
[ "${failed}" -eq 0 ]
