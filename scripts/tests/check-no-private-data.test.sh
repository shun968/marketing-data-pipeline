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

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

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
  cleanup_workdir
}

# assert_exit <期待する終了コード> <ケース名> [スクリプトへの引数...]
assert_exit() {
  local expected="$1" name="$2" actual=0
  shift 2
  ./scripts/check-no-private-data.sh "$@" > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -eq "${expected}" ]; then
    pass "${name}"
  else
    fail "${name}" "${expected}" "${actual}"
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

# .env.example はキーを含まないテンプレートで、追跡が前提。
# .env.* にマッチさせると追跡済みファイルで恒久的に止まる
setup
printf 'YOUTUBE_API_KEY=\n' > sns-collector/.env.example
git add -f sns-collector/.env.example
assert_exit 0 ".env.exampleを誤検知しない"
teardown

setup
printf 'YOUTUBE_API_KEY=\n' > .env.sample
git add -f .env.sample
assert_exit 0 ".env.sampleを誤検知しない"
teardown

# テンプレートであっても、実キーが書かれていれば止める
setup
printf 'GOOGLE_API_KEY=%s%s\n' 'AIza' "$(printf 'B%.0s' {1..35})" > sns-collector/.env.example
git add -f sns-collector/.env.example
assert_exit 1 ".env.exampleに実キーが書かれていれば検出する"
teardown

setup
git commit -qm init
assert_exit 0 "stagedが空なら何もしない"
teardown

# --- CI用モード ---
#
# CIにはステージング領域が無い。既定モードのまま実行すると対象が常に0件になり、
# 「通っているのに何も見ていない」状態になるため、範囲指定モードが要る。

setup
git commit -qm init
base="$(git rev-parse HEAD)"
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > leaked.py
git add leaked.py
git commit -qm leak
assert_exit 1 "--range: 範囲内のコミットに含まれる秘匿情報を検出する" --range "${base}...HEAD"
teardown

setup
git commit -qm init
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > leaked.py
git add leaked.py
git commit -qm leak
base="$(git rev-parse HEAD)"
echo '# doc' > README.md
git add README.md
git commit -qm doc
assert_exit 0 "--range: 範囲外(base以前)の秘匿情報は対象にしない" --range "${base}...HEAD"
teardown

setup
git commit -qm init
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > leaked.py
git add leaked.py
git commit -qm leak
assert_exit 1 "--all: 追跡中の全ファイルから検出する" --all
teardown

setup
git commit -qm init
echo '# 通常のドキュメント' > README.md
git add README.md
git commit -qm doc
assert_exit 0 "--all: 問題が無ければ通す" --all
teardown

setup
git commit -qm init
assert_exit 2 "--range に引数が無ければ使い方を示して終了する" --range
teardown

setup
git commit -qm init
assert_exit 2 "未知のオプションを拒否する" --unknown
teardown

# --range の直後にオプションが来るのはタイポ。範囲として解釈すると
# git が失敗して0件になり、黙って通ってしまう
setup
git commit -qm init
assert_exit 2 "--range の値がオプションなら拒否する" --range --all
teardown

# 【最重要】gitが失敗したら必ず落ちること。
# mapfile < <(git ...) はプロセス置換であり set -e の対象外になるため、
# 解決できない範囲を渡すと fatal を出しつつ 0 で終了する。
# ゲートが緑になって0件しか見ていない状態になり、このモードの意味が消える。
setup
git commit -qm init
assert_exit 1 "解決できない範囲を渡したら失敗する（黙って通さない）" --range "deadbeef...HEAD"
teardown

# ファイル一覧は範囲から取るのに内容をHEAD固定で読むと、チェックアウト位置が
# 範囲headと違う場合に git show が失敗し、空文字として検査対象から外れる
setup
git commit -qm init
base="$(git rev-parse HEAD)"
printf 'key = "%s%s"\n' 'sk-ant-' "$(printf 'A%.0s' {1..30})" > leaked.py
git add leaked.py
git commit -qm leak
head="$(git rev-parse HEAD)"
git checkout -q "${base}"
assert_exit 1 "HEADが範囲headと異なっても範囲内の秘匿情報を検出する" --range "${base}...${head}"
teardown

# case の * は / にもマッチする。許可リストを非公開ディレクトリより前に置くと
# sns-collector/data/.env.example が検査1をすり抜ける
setup
mkdir -p sns-collector/data
printf 'GOOGLE_API_KEY=dummy\n' > sns-collector/data/.env.example
git add -f sns-collector/data/.env.example
assert_exit 1 "非公開ディレクトリ配下の.env.exampleは許可しない"
teardown

suite_end
