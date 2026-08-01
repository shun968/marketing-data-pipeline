#!/usr/bin/env bash
set -euo pipefail

# scripts/check-repo-conventions.sh の回帰テスト。
#
# この検査は「規約を守る仕組みが在るか」を見る。誤検知すると、
# 規約を満たしているのにコミットできない状態になるため、
# 検知すべき例と検知してはいけない例を対で書く。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-repo-conventions.sh"

passed=0
failed=0
workdir=""

# 規約を満たした状態の使い捨てリポジトリを作る。
# 各ケースはここから1点だけ崩して検知を確かめる
setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
  git init -q .
  mkdir -p scripts/tests .github/workflows

  cp "${SCRIPT}" scripts/check-repo-conventions.sh
  echo '#!/usr/bin/env bash' > scripts/tests/check-repo-conventions.test.sh

  printf 'shopt -s nullglob\nsuites=(*.test.sh)\n' > scripts/tests/run-all.sh

  printf 'pre-commit:\n  jobs:\n    - run: ./scripts/tests/run-all.sh\n' > lefthook.yml
  printf 'jobs:\n  guards:\n    steps:\n      - run: ./scripts/tests/run-all.sh\n' \
    > .github/workflows/ci.yml
  printf 'tasks:\n  test:\n    cmds:\n      - ./scripts/tests/run-all.sh\n' > Taskfile.yml

  # 検査は作業ツリーではなくindexを参照する。
  # 基準状態をindexへ入れておかないと、どのケースも対象0件で素通りする
  git add -A
}

teardown() {
  cd /
  [ -n "${workdir}" ] && rm -rf "${workdir}"
}

# assert_exit <期待する終了コード> <ケース名>
assert_exit() {
  local expected="$1" name="$2" actual=0
  ./scripts/check-repo-conventions.sh > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected} / 実際: ${actual}）"
    failed=$((failed + 1))
  fi
}

echo "check-repo-conventions.sh"

setup
assert_exit 0 "規約を満たした状態を通す"
teardown

# --- 1. 検査スクリプトのテスト同伴 ---

setup
echo '#!/usr/bin/env bash' > scripts/check-something.sh
git add scripts/check-something.sh
assert_exit 1 "検知: check-*.sh にテストが無い"
teardown

# 作業ツリーを見ると、未追跡の一時スクリプトがあるだけで
# 無関係なコミットまで止まる
setup
echo '#!/usr/bin/env bash' > scripts/check-scratch.sh
assert_exit 0 "誤検知しない: 未追跡の一時スクリプト"
teardown

# 逆にテスト側を作業ツリーで見ると、テストを add し忘れたまま
# 検査スクリプトだけをコミットできてしまう
setup
echo '#!/usr/bin/env bash' > scripts/check-something.sh
echo '#!/usr/bin/env bash' > scripts/tests/check-something.test.sh
git add scripts/check-something.sh
assert_exit 1 "検知: テストが未追跡のまま検査スクリプトだけstaged"
teardown

setup
echo '#!/usr/bin/env bash' > scripts/lint-something.sh
git add scripts/lint-something.sh
assert_exit 1 "検知: lint-*.sh にテストが無い"
teardown

setup
echo '#!/usr/bin/env bash' > scripts/check-something.sh
echo '#!/usr/bin/env bash' > scripts/tests/check-something.test.sh
git add -A
assert_exit 0 "誤検知しない: テストが在る"
teardown

# 検査スクリプト以外にテストを要求しない
setup
echo '#!/usr/bin/env bash' > scripts/suggest-commit-msg.sh
git add -A
assert_exit 0 "誤検知しない: 検査スクリプト以外"
teardown

# --- 2. テスト一覧の直接列挙 ---

setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/tests/foo.test.sh\n' > lefthook.yml
assert_exit 1 "検知: lefthookがテストを直接列挙"
teardown

setup
printf 'jobs:\n  guards:\n    steps:\n      - run: ./scripts/tests/foo.test.sh\n' \
  > .github/workflows/ci.yml
assert_exit 1 "検知: CIがテストを直接列挙"
teardown

# 説明文でグロブに言及するのは列挙ではない。
# ここを弾くと運用の説明が書けなくなる
setup
printf 'tasks:\n  test:\n    summary: |\n      対象は scripts/tests/*.test.sh で決まる\n    cmds:\n      - ./scripts/tests/run-all.sh\n' \
  > Taskfile.yml
assert_exit 0 "誤検知しない: 説明文中のグロブ表記"
teardown

# --- 3. run-all.sh が列挙になっていないか ---

setup
printf 'suites=(check-foo.test.sh check-bar.test.sh)\n' > scripts/tests/run-all.sh
assert_exit 1 "検知: run-all.shがテスト名を直接列挙"
teardown

setup
printf '# 例: check-foo.test.sh のような具体名を書かない\nsuites=(*.test.sh)\n' \
  > scripts/tests/run-all.sh
assert_exit 0 "誤検知しない: コメント中の具体名"
teardown

echo "  ---"
echo "  成功 ${passed} / 失敗 ${failed}"
[ "${failed}" -eq 0 ]
