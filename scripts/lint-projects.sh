#!/usr/bin/env bash
# -e: コマンドが失敗(終了コード非0)したら即座にスクリプトを中断する
# -u: 未定義の変数を参照したらエラーにする(タイポ等に気づける)
# -o pipefail: パイプ(cmd1 | cmd2)内で最初に失敗したコマンドの終了コードを採用する
#              (デフォルトは最後のコマンドの終了コードのみで判定されるため、
#               途中のコマンドの失敗が握りつぶされてしまう)
set -euo pipefail

# リポジトリ直下の各サブディレクトリのうち、package.jsonに"lint"スクリプトを持つものを対象に
# npm run lint を実行する(tutorial/ 以外にプロジェクトが増えても自動的に対象になる)。
#
# 使い方:
#   scripts/lint-projects.sh                # 全対象プロジェクトをlint
#   scripts/lint-projects.sh --staged-only   # git staged中の変更を含むプロジェクトのみlint(pre-commit用)

STAGED_ONLY="${1:-}"

if [ "${STAGED_ONLY}" = "--staged-only" ]; then
  # --cached: 作業ツリーではなくindex(git add済みの内容)を比較対象にする
  # --name-only: 差分の中身ではなく、変更されたファイルパスのみを出力する
  # --diff-filter=ACM: 変更種別をAdded/Copied/Modifiedに限定する
  #                     (Deleted等を含めると、実体の無いファイルパスに対してlint対象ディレクトリ判定してしまうため)
  staged_files="$(git diff --cached --name-only --diff-filter=ACM)"
fi

for pkg in */package.json; do
  [ -f "${pkg}" ] || continue
  dir="${pkg%/package.json}"

  # -q: マッチ有無だけを終了コードで返し、出力はしない
  # '"lint"[[:space:]]*:' : package.json内の "lint": キーを検出するパターン
  #                         (コロン前の空白有無や整形差異を吸収するため[[:space:]]*を挟んでいる。
  #                          jq等のJSONパーサーを使わない簡易チェックのため、
  #                          コメント文字列中に偶然同じ並びが出現する等の誤検知はしない前提の割り切り)
  # || continue: マッチしなければ(=lintスクリプト無し)このディレクトリはスキップして次へ
  grep -q '"lint"[[:space:]]*:' "${pkg}" || continue

  if [ "${STAGED_ONLY}" = "--staged-only" ]; then
    echo "${staged_files}" | grep -q "^${dir}/" || continue
  fi

  echo "==> lint: ${dir}"
  (cd "${dir}" && npm run lint)
done
