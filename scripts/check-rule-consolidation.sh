#!/usr/bin/env bash
set -euo pipefail

# 規約を定義するファイルを変更したとき、全体を見直して統合したかを人に確認する。
#
# なぜ機械検査ではなく承認フローなのか:
#   「同じ文言が2箇所にある」は scripts/check-doc-duplication.sh が機械的に判定できる。
#   しかし「この規約は既存のどれかに畳めるか」「表の行とスキルのどちらが正か」は
#   文言が一致しないため検出できず、判定には意図が要る。
#   これを正規表現で近似すると、誤検知が増えて --no-verify の常用を招く。
#   機械化できないものは、機械化したふりをせず人に投げる。
#
# 速度を落とさないための限定:
#   **規約を定義するファイルがstagedに入っているときだけ聞く。**
#   通常の実装コミットでは何も出さずに終わる。
#   何でも承認フローに落とすと、承認自体が形骸化して意味を失う。
#
# 端末が無い場合(CI・スクリプト経由のコミット)はスキップする。
#   答えられない相手に聞いても止めるだけで、CIには
#   check-doc-duplication.sh という機械検査の側が残る。
#
# 使い方:
#   scripts/check-rule-consolidation.sh
#
# テスト: scripts/tests/check-rule-consolidation.test.sh

root="$(git rev-parse --show-toplevel)"
cd "${root}"

# 規約を定義する場所。ここが増えたら追記する
RULE_PATHS=(
  'CLAUDE.md'
  '*/CLAUDE.md'
  '.claude/skills/*'
  'lefthook.yml'
  'Taskfile.yml'
  'commitlint.config.js'
  '.github/workflows/*'
  'scripts/check-*.sh'
  'scripts/lint-*.sh'
)

staged_file="$(mktemp)"
trap 'rm -f "${staged_file}"' EXIT

if ! git diff --cached --name-only -z --diff-filter=ACMR -- "${RULE_PATHS[@]}" > "${staged_file}"; then
  echo "stagedの一覧を取得できなかったため中断する" >&2
  exit 1
fi
mapfile -d '' -t changed < "${staged_file}"

[ "${#changed[@]}" -gt 0 ] || exit 0

# テストから対話経路を検証するための強制フラグ。
# 質問を出す側にしか倒せないため、迂回には使えない
if [ "${RULE_REVIEW_ASSUME_TTY:-0}" != "1" ] && [ ! -t 0 ]; then
  echo "規約ファイルの変更を検出したが、端末が無いため統合確認をスキップした。" >&2
  exit 0
fi

{
  echo ""
  echo "規約を定義するファイルを変更している:"
  printf '  - %s\n' "${changed[@]}"
  echo ""
  echo "コミット前に、追加した規約について次を確認する。"
  echo "  1. 既存の規約と重ならないか。重なるなら既存側へ畳む"
  echo "  2. 正となる場所は1つか。他は参照だけにする"
  echo "  3. 機械検査に変換できないか。できるなら散文ではなく検査を足す"
  echo "  4. 不要になった記述を消したか"
  echo ""
} >&2

printf '統合整理を確認したか [y/N]: ' >&2
answer=""
IFS= read -r answer || answer=""

case "${answer}" in
  y | Y | yes | YES) ;;
  *)
    {
      echo ""
      echo "中断した。見直してからコミットし直す。"
      echo "背景は scripts/check-rule-consolidation.sh の先頭コメントを参照する。"
    } >&2
    exit 1
    ;;
esac
