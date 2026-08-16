#!/usr/bin/env bash
set -euo pipefail

# scripts/check-repo-conventions.sh の回帰テスト。
#
# この検査は「規約を守る仕組みが在るか」を見る。誤検知すると、
# 規約を満たしているのにコミットできない状態になるため、
# 検知すべき例と検知してはいけない例を対で書く。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-repo-conventions.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

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
  cleanup_workdir
}

assert_exit() {
  assert_cmd_exit "$1" "$2" ./scripts/check-repo-conventions.sh
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
git add lefthook.yml
assert_exit 1 "検知: lefthookがテストを直接列挙"
teardown

setup
printf 'jobs:\n  guards:\n    steps:\n      - run: ./scripts/tests/foo.test.sh\n' \
  > .github/workflows/ci.yml
git add .github/workflows/ci.yml
assert_exit 1 "検知: CIがテストを直接列挙"
teardown

# 説明文でグロブに言及するのは列挙ではない。
# ここを弾くと運用の説明が書けなくなる
setup
printf 'tasks:\n  test:\n    summary: |\n      対象は scripts/tests/*.test.sh で決まる\n    cmds:\n      - ./scripts/tests/run-all.sh\n' \
  > Taskfile.yml
git add Taskfile.yml
assert_exit 0 "誤検知しない: 説明文中のグロブ表記"
teardown

# --- 3. run-all.sh が列挙になっていないか ---

setup
printf 'suites=(check-foo.test.sh check-bar.test.sh)\n' > scripts/tests/run-all.sh
git add scripts/tests/run-all.sh
assert_exit 1 "検知: run-all.shがテスト名を直接列挙"
teardown

setup
printf '# 例: check-foo.test.sh のような具体名を書かない\nsuites=(*.test.sh)\n' \
  > scripts/tests/run-all.sh
git add scripts/tests/run-all.sh
assert_exit 0 "誤検知しない: コメント中の具体名"
teardown

# 参照先がindexであること自体を固定する（理由は検査器側のコメント）
setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/tests/foo.test.sh\n' > lefthook.yml
assert_exit 0 "誤検知しない: 未stagedの作業ツリー変更"
teardown

# --- 4. 違反出力のルールID ---

# ルールIDが無いと、可変の文言やファイル名が集計キーになって推移が読めない
setup
{
  echo '#!/usr/bin/env bash'
  echo 'echo "NG: 何かがおかしい" >&2'
} > scripts/check-something.sh
echo '#!/usr/bin/env bash' > scripts/tests/check-something.test.sh
git add -A
assert_exit 1 "検知: 違反出力にルールIDが無い"
teardown

setup
{
  echo '#!/usr/bin/env bash'
  echo 'echo "NG: [some-rule] 何かがおかしい" >&2'
} > scripts/check-something.sh
echo '#!/usr/bin/env bash' > scripts/tests/check-something.test.sh
git add -A
assert_exit 0 "誤検知しない: ルールIDがある"
teardown

# ルールの解説そのものを弾くと、検査器に背景が書けなくなる
setup
{
  echo '#!/usr/bin/env bash'
  echo '# 違反は "NG: 種別" ではなく "NG: [id] 種別" の形で出すこと'
  echo 'echo "NG: [some-rule] 何かがおかしい" >&2'
} > scripts/check-something.sh
echo '#!/usr/bin/env bash' > scripts/tests/check-something.test.sh
git add -A
assert_exit 0 "誤検知しない: コメント行のNG表記"
teardown

# lint系は shellcheck などの書式をそのまま流すため、この規約の対象外
setup
{
  echo '#!/usr/bin/env bash'
  echo 'echo "NG: ルールIDの無い出力" >&2'
} > scripts/lint-something.sh
echo '#!/usr/bin/env bash' > scripts/tests/lint-something.test.sh
git add -A
assert_exit 0 "誤検知しない: lint-*.sh は対象外"
teardown

# --- 5. pre-commitの検査が記録層を経由しているか ---

# 記録を省く影響は scripts/check-repo-conventions.sh のルール5を参照
setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/check-something.sh\n    - run: ./scripts/tests/run-all.sh\n' > lefthook.yml
git add lefthook.yml
assert_exit 1 "検知: 検査を記録層を経ずに直接呼んでいる"
teardown

setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/lint-scripts.sh --staged\n    - run: ./scripts/tests/run-all.sh\n' > lefthook.yml
git add lefthook.yml
assert_exit 1 "検知: lint系も記録層を経由する"
teardown

setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/record-check.sh x -- ./scripts/check-something.sh\n    - run: ./scripts/tests/run-all.sh\n' > lefthook.yml
git add lefthook.yml
assert_exit 0 "誤検知しない: 記録層を経由している"
teardown

# 対話的な承認フローは標準エラーを経由させると端末とのやり取りが壊れる
setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/check-rule-consolidation.sh\n    - run: ./scripts/tests/run-all.sh\n' > lefthook.yml
git add lefthook.yml
assert_exit 0 "誤検知しない: 対話的な承認フローは除外する"
teardown

# テストの実行やコミットメッセージ補助は検査ではない
setup
printf 'pre-commit:\n  jobs:\n    - run: ./scripts/tests/run-all.sh\nprepare-commit-msg:\n  jobs:\n    - run: ./scripts/suggest-commit-msg.sh {1}\n' > lefthook.yml
git add lefthook.yml
assert_exit 0 "誤検知しない: 検査以外の呼び出し"
teardown

# --- 6. プロジェクト設定のガードレール弱体化 ---

# 下限を満たした .claude/settings.json と隔離境界のファイルを書いてstageする。
# 各ケースはここから1点だけ崩す
write_settings() {
  mkdir -p .claude .devcontainer
  cat > .claude/settings.json <<'JSON'
{
  "permissions": {
    "ask": [
      "Edit(/.devcontainer/**)",
      "Edit(/scripts/**)",
      "Edit(/lefthook.yml)",
      "Edit(/.github/workflows/**)",
      "Edit(/.gitignore)",
      "Edit(/Taskfile.yml)",
      "Edit(/.claude/settings.json)",
      "Edit(/.claude/settings.local.json)"
    ],
    "deny": [
      "Read(/**/.env)",
      "Edit(/**/.env)",
      "Read(/**/secrets/**)",
      "Edit(/**/secrets/**)"
    ]
  }
}
JSON
  echo '{}' > .devcontainer/devcontainer.json
  printf '#!/usr/bin/env bash\niptables -P OUTPUT DROP\n' > .devcontainer/init-firewall.sh
  git add .claude/settings.json .devcontainer
}

# mutate_settings <jqフィルタ>: 設定を1点だけ崩してstageし直す
mutate_settings() {
  jq "$1" .claude/settings.json > .claude/settings.json.tmp
  mv .claude/settings.json.tmp .claude/settings.json
  git add .claude/settings.json
}

# settings.json が無い場合に通ることは、冒頭の「規約を満たした状態を通す」
# (fixtureに settings.json を含まない)が担保している

setup
write_settings
assert_exit 0 "誤検知しない: 設定が下限を満たしている"
teardown

setup
write_settings
mutate_settings '.permissions.deny -= ["Read(/**/.env)"]'
assert_exit 1 "検知: 秘匿情報のdenyが消えている"
teardown

setup
write_settings
mutate_settings '.permissions.ask -= ["Edit(/scripts/**)"]'
assert_exit 1 "検知: ガードレールのaskが消えている"
teardown

setup
write_settings
git rm -q --cached .devcontainer/init-firewall.sh
assert_exit 1 "検知: 隔離境界のファイアウォールが無い"
teardown

setup
write_settings
printf '#!/usr/bin/env bash\n' > .devcontainer/init-firewall.sh
git add .devcontainer/init-firewall.sh
assert_exit 1 "検知: ファイアウォールにdefault-denyが無い"
teardown

# 取り消せない操作の常時許可（#76）。
# 誤検知は allow を書けなくするため、通すべき隣接ケースを同じ数だけ置く
setup
write_settings
mutate_settings '.permissions.allow = ["Bash(gh pr merge:*)"]'
assert_exit 1 "検知: allow に gh pr merge がある"
teardown

setup
write_settings
mutate_settings '.permissions.allow = ["Bash(gh  pr   merge --squash)"]'
assert_exit 1 "検知: 空白の入り方が違っても gh pr merge を捕まえる"
teardown

setup
write_settings
mutate_settings '.permissions.allow = ["Bash(gh pr create:*)", "Bash(gh pr view:*)"]'
assert_exit 0 "誤検知しない: マージ以外の gh pr サブコマンド"
teardown

setup
write_settings
mutate_settings '.permissions.allow = ["Bash(git merge:*)"]'
assert_exit 0 "誤検知しない: 別コマンドの merge"
teardown

setup
write_settings
mutate_settings 'del(.permissions.allow)'
assert_exit 0 "誤検知しない: allow が無い"
teardown

# 参照先はindex。作業ツリーだけの変更で無関係なコミットを止めない
setup
write_settings
jq 'del(.permissions.deny)' .claude/settings.json > .claude/settings.json.tmp
mv .claude/settings.json.tmp .claude/settings.json
assert_exit 0 "誤検知しない: 未stagedの設定変更"
teardown

suite_end
