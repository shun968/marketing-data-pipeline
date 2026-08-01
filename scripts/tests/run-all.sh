#!/usr/bin/env bash
set -euo pipefail

# scripts/ 配下の検査スクリプトの回帰テストをまとめて実行する。
# lefthook・Taskfile・CI はすべてこのスクリプトを呼ぶ。
#
# 一覧を複数箇所に書かない:
#   テストの並びを呼び出し側それぞれに書くと、テストを1本足したときに
#   どこかが漏れる。実際に lint-scripts.test.sh を追加した際、
#   Taskfile と CI は更新したが lefthook が漏れた。
#
# 対象は *.test.sh の列挙で自動的に決まる。テストを足したら勝手に走る。

cd "$(dirname "${BASH_SOURCE[0]}")"

shopt -s nullglob
suites=(*.test.sh)

if [ "${#suites[@]}" -eq 0 ]; then
  echo "テストが1本も見つからない。列挙条件が壊れている可能性がある" >&2
  exit 1
fi

for suite in "${suites[@]}"; do
  "./${suite}"
done
