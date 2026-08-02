#!/usr/bin/env bash
set -euo pipefail

# scripts/check-rule-consolidation.sh の回帰テスト。
#
# 承認フローは「聞きすぎない」ことが要件である。
# 規約と無関係なコミットで質問が出ると、y の連打が習慣化して承認が形骸化する。
# 「聞くべきケース」と同じ数だけ「聞いてはいけないケース」を置く。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-rule-consolidation.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup() {
  new_git_workdir
}

teardown() {
  cleanup_workdir
}

# 端末が無い状態での実行(CI・スクリプト経由のコミット)
assert_exit() {
  assert_cmd_exit "$1" "$2" "${SCRIPT}"
}

# 端末があるものとして実行し、回答を標準入力から与える
# assert_answer <期待する終了コード> <ケース名> <回答>
assert_answer() {
  local actual=0
  RULE_REVIEW_ASSUME_TTY=1 "${SCRIPT}" <<< "${3-y}" > /dev/null 2>&1 || actual=$?
  check_exit "$1" "$2" "${actual}"
}

echo "check-rule-consolidation.sh"

# --- 聞かないケース ---

setup
mkdir -p src
echo "print('hello')" > src/main.py
git add -A
assert_answer 0 "聞かない: 規約と無関係なファイルだけ"
teardown

setup
echo "" > empty.txt
git add -A
assert_answer 0 "聞かない: stagedに規約ファイルが無い"
teardown

# 作業ツリーだけの編集で質問が出ると、コミットしていないのに止められる
setup
echo "# 規約" > CLAUDE.md
git add -A
git commit -qm init
echo "# 規約を編集した" > CLAUDE.md
assert_answer 0 "聞かない: 未stagedの規約ファイル変更"
teardown

# --- 聞くケース ---

setup
echo "# 規約" > CLAUDE.md
git add -A
assert_answer 0 "聞く: CLAUDE.md を変更して y と答えれば通る"
teardown

setup
echo "# 規約" > CLAUDE.md
git add -A
assert_answer 1 "聞く: n と答えれば止まる" "n"
teardown

setup
echo "# 規約" > CLAUDE.md
git add -A
assert_answer 1 "既定は否認（未入力で通さない）" ""
teardown

setup
mkdir -p sns-collector
echo "# 領域の規約" > sns-collector/CLAUDE.md
git add -A
assert_answer 1 "聞く: サブディレクトリの CLAUDE.md" "n"
teardown

setup
mkdir -p .claude/skills/adr
echo "# 手順" > .claude/skills/adr/SKILL.md
git add -A
assert_answer 1 "聞く: スキル" "n"
teardown

setup
echo "pre-commit:" > lefthook.yml
git add -A
assert_answer 1 "聞く: lefthook.yml" "n"
teardown

setup
mkdir -p scripts
echo "#!/usr/bin/env bash" > scripts/check-example.sh
git add -A
assert_answer 1 "聞く: 検査スクリプト" "n"
teardown

setup
mkdir -p .github/workflows
echo "name: ci" > .github/workflows/ci.yml
git add -A
assert_answer 1 "聞く: CI定義" "n"
teardown

# --- 端末が無い場合 ---

# CIやスクリプト経由のコミットでは答えられない。
# ここで止めると自動化が壊れるだけで、機械検査の側は別途CIで走る
setup
echo "# 規約" > CLAUDE.md
git add -A
assert_exit 0 "端末が無ければスキップする"
teardown

suite_end
