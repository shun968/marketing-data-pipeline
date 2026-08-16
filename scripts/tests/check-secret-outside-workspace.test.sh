#!/usr/bin/env bash
set -euo pipefail

# scripts/check-secret-outside-workspace.sh の回帰テスト。
#
# この検査は毎コミットで走り、誤検知すると鍵と無関係な作業まで止まる。
# 止まった側は --no-verify へ逃げるため(CLAUDE.md)、
# 「検知すべき例」と「検知してはいけない例」を対で書く。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-secret-outside-workspace.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup() {
  new_git_workdir
  mkdir -p sns-collector
}

teardown() {
  cleanup_workdir
}

assert_exit() {
  assert_cmd_exit "$1" "$2" "${SCRIPT}"
}

suite_begin "check-secret-outside-workspace.sh"

# --- 検知すべき ---

setup
printf 'YOUTUBE_API_KEY=x\n' > sns-collector/.env
assert_exit 1 "収集インスタンス配下の .env を検知する"
teardown

setup
printf 'YOUTUBE_API_KEY=x\n' > .env
assert_exit 1 "リポジトリ直下の .env を検知する"
teardown

setup
printf 'YOUTUBE_API_KEY=x\n' > sns-collector/.env.local
assert_exit 1 "接尾辞つき(.env.local)も検知する"
teardown

# 非ASCIIのディレクトリ名。-print0 / mapfile -d '' で受けていないと
# パスが途中で分割され、静かに検出漏れになる
setup
mkdir -p '収集/設定'
printf 'YOUTUBE_API_KEY=x\n' > '収集/設定/.env'
assert_exit 1 "非ASCIIパス配下の .env を検知する"
teardown

# --- 検知してはいけない ---

setup
assert_exit 0 "環境ファイルが無ければ通る"
teardown

setup
printf 'YOUTUBE_API_KEY=\n' > sns-collector/.env.example
printf 'YOUTUBE_API_KEY=\n' > sns-collector/.env.sample
assert_exit 0 "テンプレート(.env.example / .env.sample)は対象外"
teardown

# 依存物が同梱するサンプルまで拾うと、uv sync しただけでコミットできなくなる
setup
mkdir -p sns-collector/.venv/lib node_modules/pkg
printf 'KEY=x\n' > sns-collector/.venv/lib/.env
printf 'KEY=x\n' > node_modules/pkg/.env
assert_exit 0 "除外ディレクトリ配下は対象外"
teardown

# `.env` という名前のディレクトリは鍵ではない
setup
mkdir -p sns-collector/.env
assert_exit 0 "同名のディレクトリでは発火しない"
teardown

suite_end
