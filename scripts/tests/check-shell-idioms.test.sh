#!/usr/bin/env bash
#
# フィクスチャを単一引用符で保持する必要があるため SC2016 を無効化する。
# 事情は検査器側の先頭コメントと同じ。
# shellcheck disable=SC2016
set -euo pipefail

# scripts/check-shell-idioms.sh の回帰テスト。
#
# **ルール1つにつき「検知すべき例」と「検知してはいけない例」を対で書く。**
# grepベースの禁止パターンは誤検知しやすく、誤検知は --no-verify の常用を招いて
# ゲートそのものを無効化する(CLAUDE.md)。
#
# 検査対象のイディオムは、このファイル自身に素で書くと自己検出される。
# printf の引数として実行時に組み立てることで避けている。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-shell-idioms.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
}

teardown() {
  cleanup_workdir
}

assert_exit() {
  assert_cmd_exit "$1" "$2" "${SCRIPT}" target.sh
}

header() {
  {
    echo '#!/usr/bin/env bash'
    echo 'set -euo pipefail'
  } > target.sh
}

echo "check-shell-idioms.sh"

# --- ルール1: gitのファイル一覧に -z が無い ---

setup
header
printf 'git %s "*.sh" > "${tmp}"\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: git ls-files に -z が無い"
teardown

setup
header
printf 'git diff --cached %s > "${tmp}"\n' '--name-only' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: --name-only に -z が無い"
teardown

setup
header
printf 'git %s -z "*.sh" > "${tmp}"\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: -z がある"
teardown

# 罠を解説するコメントが書けなくなると、再発防止の記録そのものが残せない
setup
header
printf '# %s を -z なしで使わないこと\n' 'git ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: コメント行"
teardown

# 内容が欲しいだけの git diff はパス一覧ではない
setup
header
printf 'DIFF="$(git diff --cached)"\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: パス一覧ではない git diff"
teardown

# --- ルール2: gitの出力をプロセス置換で読んでいる ---

setup
header
printf 'mapfile -d "" -t files < <(git %s -z)\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: git出力のプロセス置換"
teardown

setup
header
printf 'if ! git %s -z > "${tmp}"; then exit 1; fi\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
printf 'mapfile -d "" -t files < "${tmp}"\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: 一時ファイル経由"
teardown

# git以外のプロセス置換まで禁止すると誤検知が増える。実際に事故を起こした形だけを対象にする
setup
header
printf 'while read -r line; do echo "${line}"; done < <(sort input.txt)\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: git以外のプロセス置換"
teardown

# --- ルール3: gitのコマンド置換をそのまま cd に渡している ---

setup
header
printf 'cd "$(git %s --show-toplevel)"\n' 'rev-parse' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: cd に git のコマンド置換"
teardown

setup
header
printf 'root="$(git %s --show-toplevel)"\n' 'rev-parse' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
printf 'cd "${root}"\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: 代入してから cd"
teardown

# `cd "$(dirname ...)"` は失敗しない。ここを弾くと既存の全テストが書けなくなる
setup
header
printf 'cd "$(dirname "${BASH_SOURCE[0]}")"\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: cd に dirname のコマンド置換"
teardown

# --- コメント判定と除外条件の境界 ---

# `[[:space:]]*'#'*` はグロブでは「空白1文字 + 任意 + # + 任意」の意味になり、
# 行末コメントの付いたインデント行を丸ごとコメント扱いして検査を飛ばしていた
setup
header
printf '  mapfile -t files < <(git %s "*.sh")   # 対象を集める\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: 行末コメントの付いたインデント行を飛ばさない"
teardown

setup
header
printf '  # mapfile -t files < <(git %s "*.sh") は書かない\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: インデントされたコメント行"
teardown

# 除外条件を行全体で見ると、無関係な -z が検出を抑止する
setup
header
printf 'if [ -z "${filter}" ]; then files=$(git %s "*.sh"); fi\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: 無関係な -z では抑止されない"
teardown

# 行継続を畳まないと、次行にある -z を見落として誤検知する
setup
header
printf 'git diff --cached %s \\\n  -z > "${tmp}"\n' '--name-only' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: 行継続の次行に -z がある"
teardown

# --- 適用除外マーカー ---

# 検査器自身やテストのフィクスチャは、検出対象の形を書かざるを得ない。
# 除外が無いと自己検出で恒久的に落ちる
setup
header
printf 'git %s "*.sh"  # idiom-ok: 理由\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "idiom-ok マーカーのある行を除外する"
teardown

# 除外は行単位。ファイル全体を除外すると同じファイルの本物の再発を見逃す
setup
header
printf 'git %s "*.sh"  # idiom-ok: 理由\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
printf 'git %s "*.md"\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "マーカーは行単位で、同じファイルの他の行は検査する"
teardown

# 文字列リテラルに書くだけで検査を無効化できてはいけない
setup
header
printf 'echo "idiom-ok と書く"; git %s > b\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "マーカーはコメント部のみ有効（文字列内では効かない）"
teardown

# --- 行をまたぐ形・区切りの扱い ---

# `< <(` と git が別行に分かれた形。畳まないと検出できない
setup
header
printf 'mapfile -d "" -t x < <(\n  git %s -z\n)\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: プロセス置換が複数行にまたがる"
teardown

# パイプで区切ると `< <(printf ... | git ...)` が2つに割れて検査が効かなくなる
setup
header
printf 'mapfile -d "" -t x < <(printf "%%s" "$a" | git check-ignore -z --stdin)\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: プロセス置換の中がパイプでも分割しない"
teardown

# シェルはコメント内で行を継続しない。畳むと直後の実コード行までコメント扱いになる
setup
header
printf '# 説明 \\\nmapfile -t f < <(git %s "*.sh")\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: コメント末尾の \\ で次行を巻き込まない"
teardown

# 先頭の -z が同じ行の後続コマンドまで免除してはいけない
setup
header
printf 'git %s -z > a; git %s > b\n' 'ls-files' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 1 "検知: 同一行の2つ目のgitに -z が無い"
teardown

setup
header
printf 'git %s -z > a; git %s -z > b\n' 'ls-files' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: 同一行の両方に -z がある"
teardown

# 存在確認は出力を捨てるため -z に意味が無い。誤検知するとマーカー付与を強いる
setup
header
printf 'git %s --error-unmatch "$f" >/dev/null\n' 'ls-files' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "誤検知しない: --error-unmatch は存在確認"
teardown

# --- その他 ---

setup
header
printf 'echo "問題のないスクリプト"\n' >> target.sh  # idiom-ok: 検査対象のフィクスチャ
assert_exit 0 "問題のないスクリプトを通す"
teardown

setup
if "${SCRIPT}" > /dev/null 2>&1; then
  echo "  ok   引数が無ければ何もしない"
  passed=$((passed + 1))
else
  echo "  FAIL 引数が無ければ何もしない"
  failed=$((failed + 1))
fi
teardown

suite_end
