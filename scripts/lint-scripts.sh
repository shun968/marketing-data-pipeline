#!/usr/bin/env bash
set -euo pipefail

# シェルスクリプトとYAMLの静的検査。CIの guards ジョブと `task lint-scripts` の実体。
#
# なぜ必要か:
#   scripts/check-*.sh は「収集データを外部へ出さない」という最重要制約を守る
#   唯一の機構である。回帰テストは追加済みだが、未クォート変数や
#   `set -euo pipefail` 下での終了コード伝播といった静的な問題は、
#   テストが通っていても残る。
#   YAMLについては config/keywords.yaml の構文崩れが収集失敗に直結する。
#
# CIとローカルで実装を分けない:
#   同じ検査を2箇所に書くと、手元で通ったものがCIで落ちる。
#   CI(.github/workflows/ci.yml)はこのスクリプトを呼ぶだけにしてある。
#
# 使い方:
#   scripts/lint-scripts.sh            追跡済み + 未追跡を検査する(手元での既定)
#   scripts/lint-scripts.sh --staged   stagedのファイルだけを検査する(pre-commit)
#   scripts/lint-scripts.sh --all      追跡済みファイルすべてを検査する(CI)
#
# --staged が index ではなく作業ツリーの内容を読むことについて:
#   check-no-private-data.sh は `git show ":${f}"` で index を読む。秘匿情報は
#   一度通すと取り返しがつかず、`git add` 後に作業ツリーだけ直した状態を
#   見逃せないため。lintの指摘は通ってしまっても実害が小さく、CIが --all で
#   マージ対象の状態を検査するので、ここでは実装の単純さを優先している。
#
# テスト: scripts/tests/lint-scripts.test.sh

# バージョンを固定する。ubuntu-latest のプリインストール版を使わない理由が
# 「ランナー更新で指摘が増減する」である以上、uvx側で解決を最新に委ねると
# 同じ問題が形を変えて残る(上流リリースだけでCIが赤くなる)
SHELLCHECK_PKG="shellcheck-py==0.11.0.1"
YAMLLINT_PKG="yamllint==1.38.0"

mode="worktree"
case "${1:-}" in
  "") ;;
  --staged) mode="staged" ;;
  --all) mode="all" ;;
  *)
    echo "不明な引数: $1（--staged / --all のみ）" >&2
    exit 2
    ;;
esac

# `cd "$(git rev-parse ...)"` と書かない。コマンド置換が失敗しても
# bashの `cd ""` は成功扱いになり、set -e を素通りする。
# 代入にすれば git の終了コードがそのまま伝わる
root="$(git rev-parse --show-toplevel)"
cd "${root}"

list_file="$(mktemp)"
trap 'rm -f "${list_file}"' EXIT

FILES=()

# collect <パスパターン...> → FILES に結果を入れる
#
# `mapfile -t FILES < <(git ls-files ...)` と書かない。プロセス置換の中は
# set -e の対象外で、git が失敗しても配列が空になるだけで済んでしまう。
# 「対象なし」と表示して exit 0 する = 何も検査していないのにCIが緑になる。
# 一時ファイルへのリダイレクトにすれば git の失敗でそのまま落ちる。
#
# -z を付ける理由: 既定(core.quotePath=true)では非ASCIIパスが
# "\350\250\255\345\256\232.yml" 形式へクォートされ、実在しないパスとして
# linterへ渡り、日本語名のファイルが1つあるだけで全コミットが落ちる。
collect() {
  case "${mode}" in
    staged) git diff --cached --name-only -z --diff-filter=ACMR -- "$@" > "${list_file}" ;;
    all) git ls-files -z -- "$@" > "${list_file}" ;;
    *) git ls-files -z --cached --others --exclude-standard -- "$@" > "${list_file}" ;;
  esac

  FILES=()
  local f
  while IFS= read -r -d '' f; do
    # `git rm` ではなく `rm` で消したファイルは index に残る。
    # 実体が無いパスを渡すと linter が "does not exist" で中断し、
    # 無関係なコミットまで巻き添えで止まる
    [ -f "${f}" ] && FILES+=("${f}")
  done < "${list_file}"
}

echo "==> shellcheck"
collect '*.sh'
if [ "${#FILES[@]}" -gt 0 ]; then
  # -x: source 先を追って解析する。
  #     無いと共通処理を切り出しただけで SC1091(info) が出て赤くなり、
  #     共通化を諦めるか無効化コメントを全ファイルへ書き足すことになる
  # --source-path=SCRIPTDIR: source 先をスクリプト自身の位置から解決する。
  #     既定はカレントディレクトリ基準のため、リポジトリルートから実行すると
  #     `$(dirname "${BASH_SOURCE[0]}")/lib.sh` を見つけられない
  uvx --from "${SHELLCHECK_PKG}" shellcheck -x --source-path=SCRIPTDIR "${FILES[@]}"
  echo "  ${#FILES[@]} ファイル: 指摘なし"
else
  echo "  対象なし"
fi

# 上のlinterが見るのは一般的なシェルの誤りで、このリポジトリで実際に
# 事故を起こしたイディオム(非ASCIIパスの取りこぼし等)は検出できない。
# 直前の collect の結果をそのまま使い、配線箇所を増やさない
echo "==> 禁止イディオム"
if [ "${#FILES[@]}" -gt 0 ]; then
  "${root}/scripts/check-shell-idioms.sh" "${FILES[@]}"
  echo "  ${#FILES[@]} ファイル: 指摘なし"
else
  echo "  対象なし"
fi

# --strict: warning も終了コードに反映させる。
# 体裁ルールは .yamllint.yml で無効化済みのため、ここで出る warning は
# キー重複など実害のあるものに限られる
echo "==> yamllint"
collect '*.yml' '*.yaml'
if [ "${#FILES[@]}" -gt 0 ]; then
  uvx --from "${YAMLLINT_PKG}" yamllint --strict "${FILES[@]}"
  echo "  ${#FILES[@]} ファイル: 指摘なし"
else
  echo "  対象なし"
fi
