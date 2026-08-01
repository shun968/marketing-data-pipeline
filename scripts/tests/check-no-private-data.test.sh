#!/usr/bin/env bash
set -euo pipefail

# scripts/check-no-private-data.sh の回帰テスト。
#
# 秘匿情報らしき文字列は printf の引数として実行時に組み立てる。
# このファイル自身に完全な形で書くと、検査スクリプトが自分のテストを
# 秘匿情報として検出してしまい、テストをコミットできなくなる。
#
# **検出できることと同じ重みで、誤検知しないことをテストする。**
# CLAUDE.mdは --no-verify での迂回を禁じているため、誤検知は
# ゲートそのものを無効化する。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-no-private-data.sh"

passed=0
failed=0
workdir=""

setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
  git init -q .
  git config user.email test@example.com
  git config user.name test
  mkdir -p scripts sns-collector/data sns-collector/state
  cp "${SCRIPT}" scripts/check-no-private-data.sh
  printf 'sns-collector/data/\nsns-collector/state/\n.env\n*.log\n' > .gitignore
  git add .gitignore scripts/check-no-private-data.sh
}

teardown() {
  cd /
  [ -n "${workdir}" ] && rm -rf "${workdir}"
}

# assert_exit <期待する終了コード> <ケース名>
assert_exit() {
  local expected="$1" name="$2" actual=0
  ./scripts/check-no-private-data.sh > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected} / 実際: ${actual}）"
    failed=$((failed + 1))
  fi
}

echo "check-no-private-data.sh"

# --- 検出すべきケース ---

setup
echo '{"text":"投稿本文"}' > sns-collector/data/posts.jsonl
git add -f sns-collector/data/posts.jsonl
assert_exit 1 "収集データ(sns-collector/data/)を検出する"
teardown

setup
printf 'BLUESKY_APP_PASSWORD=%s-%s-%s-%s\n' abcd efgh ijkl mnop > .env
git add -f .env
assert_exit 1 ".envを検出する"
teardown

setup
echo 'debug' > runtime.log
git add -f runtime.log
assert_exit 1 ".gitignore対象(*.log)を検出する"
teardown

setup
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > config.py
git add config.py
assert_exit 1 "Anthropic APIキーを検出する"
teardown

setup
printf -- '-----BEGIN RSA %s KEY-----\n' PRIVATE > key.pem
git add key.pem
assert_exit 1 "秘密鍵を検出する"
teardown

setup
printf 'password: %s-%s-%s-%s\n' abcd efgh ijkl mnop > creds.yaml
git add creds.yaml
assert_exit 1 "Blueskyアプリパスワードを検出する"
teardown

# 非ASCIIパスは既定でCクォートされ、git show が失敗して黙って検査対象から外れる。
# -z を外すとこのケースが素通りする
setup
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > "収集メモ.md"
git add "収集メモ.md"
assert_exit 1 "日本語ファイル名の中の秘匿情報を検出する"
teardown

setup
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > "改行
入り.md"
git add "改行
入り.md"
assert_exit 1 "改行を含むファイル名の中の秘匿情報を検出する"
teardown

# --- 検出してはいけないケース ---

setup
echo '# 通常のドキュメント' > README.md
git add README.md
assert_exit 0 "通常のファイルは通す"
teardown

# 小文字UUIDには 4-4-4-4 が必ず含まれる。
# 境界条件を外すとUUIDを1個含むだけでコミットが止まる
setup
echo '{"session_id":"123e4567-e89b-12d3-a456-426614174000"}' > fixture.json
git add fixture.json
assert_exit 0 "UUIDをアプリパスワードとして誤検知しない"
teardown

setup
echo 'commit: 4f3a2b1c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a' > meta.txt
git add meta.txt
assert_exit 0 "コミットハッシュを誤検知しない"
teardown

setup
git commit -qm init
assert_exit 0 "stagedが空なら何もしない"
teardown

echo "  ---"
echo "  成功 ${passed} / 失敗 ${failed}"
[ "${failed}" -eq 0 ]
