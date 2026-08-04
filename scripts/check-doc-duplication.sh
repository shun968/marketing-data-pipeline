#!/usr/bin/env bash
set -euo pipefail

# 同じ規約・根拠が複数のファイルへ書き写されていないかを検査する。
#
# なぜ必要か:
#   規約は「1箇所にしか書かない」ことを前提に運用している(CLAUDE.md)。
#   ところが規約を足すたびに、根拠の説明が別のスクリプトやドキュメントへ
#   コピーされ、片方だけ更新されて食い違う。
#   レビューで気づく前提にすると、レビューを走らせなければ素通りする。
#
# 何を見るか:
#   **散文だけを見る。** 対象は
#     - シェルスクリプトのコメント行
#     - Markdown の本文行(コードフェンス内と表は除く)
#   コード行は対象外。`local expected="$1"` のような定型は重複して当然で、
#   コードの重複はテストの共通化などで別途扱う。
#
# 除外:
#   行末に `dup-ok: <理由>` を書いた行は対象外にする。
#   意図的に同じ文言を置く必要がある場合のため。
#
#   バージョン付きプロンプトどうしの重複も許す（理由は下の判定部にある）。
#
# 使い方:
#   scripts/check-doc-duplication.sh
#
# テスト: scripts/tests/check-doc-duplication.test.sh

root="$(git rev-parse --show-toplevel)"
cd "${root}"

# 短い断片まで拾うとノイズになる。1文として意味を持つ長さに限る
MIN_LENGTH="${DUP_MIN_LENGTH:-30}"

list_file="$(mktemp)"
trap 'rm -f "${list_file}"' EXIT

if ! git ls-files -z -- '*.sh' '*.md' > "${list_file}"; then
  echo "検査対象の一覧を取得できなかったため中断する" >&2
  exit 1
fi
mapfile -d '' -t targets < "${list_file}"

[ "${#targets[@]}" -gt 0 ] || exit 0

# 各行を `正規化した文<TAB>ファイル:行番号` の形へ落とし、
# 同じ文が2つ以上のファイルに出るものを重複とみなす
#
# バージョン付きプロンプト(sns-collector/prompts/extract-*.md)どうしの重複は許す。
# 版ごとに独立した成果物で、改訂しても旧版を残す（どの版で抽出したかを
# insights.extractor_version から辿るため）。v2がv1の大半を引き継ぐのは正常である。
#
# **対象から外すのではなく、プロンプト間の組み合わせだけを許す。** 外してしまうと、
# プロンプトの文言を設計書などへ書き写しても検出できない穴ができる。
#
# `dup-ok:` で個別に許可しない理由: プロンプトは抽出セッションへそのまま渡される
# ファイルであり、注釈を入れると指示文に混ざって読ませてしまう。
duplicates="$(
  awk -v min_len="${MIN_LENGTH}" '
    function is_prompt(f) { return f ~ /(^|\/)sns-collector\/prompts\/extract-[^\/]*\.md$/ }

    FNR == 1 { in_fence = 0 }

    # Markdownのコードフェンス内は散文ではない
    /^[[:space:]]*```/ { in_fence = !in_fence; next }
    in_fence { next }

    {
      line = $0

      # 意図的な重複は除外する
      if (line ~ /dup-ok/) next

      if (FILENAME ~ /\.sh$/) {
        # コメント行だけを見る
        if (line !~ /^[[:space:]]*#/) next
        sub(/^[[:space:]]*#+[[:space:]]*/, "", line)
      } else {
        # 表は語の並びが重複して当然なので除外する
        if (line ~ /^[[:space:]]*\|/) next
        sub(/^[[:space:]]*[-*>#]+[[:space:]]*/, "", line)
      }

      # 記号と空白の差を吸収する
      gsub(/[`*_、。，．,.:：]/, "", line)
      gsub(/[[:space:]]/, "", line)

      if (length(line) < min_len) next

      key = line
      if (!(key in seen_file)) { seen_file[key] = FILENAME; seen_loc[key] = FILENAME ":" FNR; next }
      if (seen_file[key] == FILENAME) next
      if (is_prompt(seen_file[key]) && is_prompt(FILENAME)) next
      if (!(key in reported)) {
        reported[key] = 1
        print seen_loc[key] "\t" FILENAME ":" FNR "\t" substr($0, 1, 100)
      }
    }
  ' "${targets[@]}"
)"

if [ -n "${duplicates}" ]; then
  count="$(printf '%s\n' "${duplicates}" | wc -l)"
  echo "NG: [doc-duplicated] 同じ記述が複数のファイルにある（${count} 件）" >&2
  echo "" >&2
  printf '%s\n' "${duplicates}" | while IFS=$'\t' read -r first second text; do
    echo "  ${first}" >&2
    echo "  ${second}" >&2
    echo "    ${text}" >&2
    echo "" >&2
  done
  cat >&2 <<'MSG'
規約や根拠は1箇所にしか書かない。正となる場所を決め、他はそこへの参照にする。
意図して同じ文言を置く必要がある行には `dup-ok: <理由>` を書く。
MSG
  exit 1
fi
