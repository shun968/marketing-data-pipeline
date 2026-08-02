#!/usr/bin/env bash
#
# 修正例として `$(...)` や `${tmp}` を含むコード片を単一引用符で保持するため、
# ファイル全体で SC2016(単一引用符内は展開されない) を無効化する。
# 展開されては困る文字列であり、指摘は常に誤検知になる。
# shellcheck disable=SC2016
set -euo pipefail

# 過去のレビュー指摘を「禁止イディオム」として機械検出する。
#
# なぜ必要か:
#   同じ指摘が別のファイルで再発している。非ASCIIパスの -z 漏れは
#   check-no-private-data.sh で直した後に lint-scripts.sh で再発し、
#   さらに check-adr-format.sh にも残っていた。
#   CLAUDE.mdに書くだけでは、新しいファイルを書く瞬間に想起されない。
#
# 運用:
#   **レビュー指摘1件 = 1ルール + テスト2件**(検知すべき例 / 検知してはいけない例)。
#   ルールを足すときは scripts/tests/check-shell-idioms.test.sh も必ず足す。
#
# メッセージには「なぜ落ちるか」と「代替コード」を書く:
#   この出力を読んで直すのは人間とは限らない。指摘だけでは直し方が伝わらず、
#   別の間違った書き換えを誘発する。
#
# 検出範囲を意図的に狭くしている:
#   grepベースの禁止パターンは誤検知しやすい。誤検知は --no-verify の常用を
#   招き、ゲートそのものを無効化する(CLAUDE.md)。
#   そのため「一般に危険な書き方」ではなく「実際に事故を起こした形」だけを
#   対象にする。例えば cd の検査は git のコマンド置換に限定し、
#   `cd "$(dirname ...)"` のような失敗しない形は対象外にする。
#
# 使い方:
#   scripts/check-shell-idioms.sh <ファイル...>
#
# テスト: scripts/tests/check-shell-idioms.test.sh

[ "$#" -gt 0 ] || exit 0

violations=0
logical_file="$(mktemp)"
trap 'rm -f "${logical_file}"' EXIT

# 物理行を論理行へ畳み、`開始行番号<TAB>内容` を出力する。
#
# 畳む対象は2つ。
#   1. 行継続(末尾の \)
#        畳まないと `git diff --name-only \` の次行にある -z を見落として誤検知する。
#        ただし**コメント行の末尾 \ では畳まない**。シェルはコメント内で行を継続せず、
#        畳むと直後の実コード行までコメント扱いになって検査が素通りする。
#   2. 閉じていないプロセス置換 `<(`
#        `< <(` と `git` が別行に分かれた形を1行として見るため。
#        畳まないと、この形の違反(実例: check-no-private-data.sh)を検出できない。
fold_continuations() {
  awk '
    function is_comment(s) { sub(/^[[:space:]]+/, "", s); return substr(s, 1, 1) == "#" }
    function open_subst(s,   i, n) {
      n = 0
      n += gsub(/<\(/, "<(", s)
      return n - gsub(/\)/, ")", s)
    }
    {
      if (pending == 0) { start = NR; buf = "" }
      cur = $0

      # コメント行の末尾 \ は継続ではない
      if (cur ~ /\\$/ && !(pending == 0 && is_comment(cur))) {
        sub(/\\$/, "", cur)
        buf = buf cur
        pending = 1
        next
      }

      buf = buf cur
      if (open_subst(buf) > 0) { pending = 1; next }

      print start "\t" buf
      buf = ""
      pending = 0
    }
    END { if (pending) print start "\t" buf }
  ' "$1"
}

# check_rule <ファイル> <検出regex> <除外regex|-> <見出し> <説明>
check_rule() {
  local file="$1" detect="$2" allow="$3" title="$4" hint="$5"
  local entry line_no line trimmed segment

  while IFS= read -r entry; do
    line_no="${entry%%$'\t'*}"
    line="${entry#*$'\t'}"

    # 先頭の空白を落としてから判定する。
    # `[[:space:]]*'#'*` のようなグロブは「空白1文字 + 任意 + # + 任意」の意味になり、
    # 行末コメントの付いたインデント行までコメント扱いして検査を丸ごと飛ばす
    trimmed="${line#"${line%%[![:space:]]*}"}"
    case "${trimmed}" in
      '#'*) continue ;;
    esac

    # 行末に `# idiom-ok: <理由>` があれば除外する。
    # テストのフィクスチャなど、検出対象の形を意図的に書く必要がある行のため。
    #
    # ファイル単位ではなく行単位にしているのは、除外範囲が広いと
    # 同じファイルの他の箇所で本物の再発を見逃すため。
    # さらに **コメント部にあるものだけ** を認める。行のどこでも良いことにすると、
    # 文字列リテラルへ書くだけで検査を無効化できてしまう
    if [[ ${line} =~ \#[^\'\"]*idiom-ok ]]; then
      continue
    fi

    # 論理行を `;` `&&` `||` で区切り、区切りごとに独立して判定する。
    # 1行に複数のコマンドを書いた場合、先頭の -z が後続のコマンドまで
    # 免除してしまうため(`git ls-files -z > a; git ls-files > b` が素通りする)。
    #
    # 単独の `|` では区切らない。パイプを割ると
    # `< <(printf ... | git check-ignore ...)` が2つに分かれ、
    # プロセス置換の検査が効かなくなる
    local -a parts=()
    local rest="${line}" part
    while [[ ${rest} =~ (\;|\&\&|\|\|) ]]; do
      part="${rest%%"${BASH_REMATCH[1]}"*}"
      parts+=("${part}")
      rest="${rest#*"${BASH_REMATCH[1]}"}"
    done
    parts+=("${rest}")

    local detected=0
    for part in "${parts[@]}"; do
      [[ ${part} =~ ${detect} ]] || continue

      # 除外条件は区切り内の、さらに git コマンド以降だけで見る。
      # 区切り全体を見ると `if [ -z "${x}" ]` のような無関係な -z が検出を抑止する
      if [ "${allow}" != "-" ]; then
        segment="${part#*git }"
        [[ ${segment} =~ ${allow} ]] && continue
      fi

      detected=1
      break
    done
    [ "${detected}" -eq 1 ] || continue

    echo "NG: ${file}:${line_no}: ${title}" >&2
    printf '%s\n' "${hint}" | sed 's/^/    /' >&2
    echo "" >&2
    violations=$((violations + 1))
  done < "${logical_file}"
}

for f in "$@"; do
  [ -f "${f}" ] || continue

  fold_continuations "${f}" > "${logical_file}"

  check_rule "${f}" \
    'git ls-files|--name-only' `# idiom-ok: 検出パターンの定義そのもの` \
    '(^|[[:space:]])(-z|--error-unmatch)([[:space:]]|$)' \
    'gitのファイル一覧に -z が無い' \
    'core.quotePath=true(既定)では非ASCIIパスが "\346\212\225..." 形式へ
クォートされ、実在しないパスとして扱われて検査から静かに漏れる。
日本語のファイル名が1つあるだけで検出漏れ、または全コミット失敗になる。

  # 修正前: mapfile -t files < <(git ls-files "*.sh")
  # 修正後: git ls-files -z "*.sh" > "${tmp}"
  #         mapfile -d "" -t files < "${tmp}"'

  check_rule "${f}" \
    '<[[:space:]]*<\(.*git[[:space:]]' \
    '-' \
    'gitの出力をプロセス置換で読んでいる' \
    'プロセス置換の中は set -e の対象外で、gitが失敗しても配列が空になるだけ。
「対象なし」と表示して終了コード0になる = 何も検査していないのに緑になる。

  # 修正前: mapfile -d "" -t files < <(git ls-files -z)
  # 修正後: if ! git ls-files -z > "${tmp}"; then
  #           echo "一覧を取得できなかったため中断する" >&2; exit 1
  #         fi
  #         mapfile -d "" -t files < "${tmp}"'

  check_rule "${f}" \
    'cd[[:space:]]+"?\$\(git' \
    '-' \
    'gitのコマンド置換をそのまま cd に渡している' \
    'コマンド置換が失敗しても bash の `cd ""` は成功扱いになり、set -e を素通りする。
gitリポジトリ外で実行したときに、意図しない場所で処理が続く。

  # 修正前: cd "$(git rev-parse --show-toplevel)"
  # 修正後: root="$(git rev-parse --show-toplevel)"   # 代入なら終了コードが伝わる
  #         cd "${root}"'
done

if [ "${violations}" -gt 0 ]; then
  echo "禁止イディオムを ${violations} 件検出した。過去のレビュー指摘の再発である。" >&2
  echo "背景と全ルールは scripts/check-shell-idioms.sh の先頭コメントを参照する。" >&2
  exit 1
fi
