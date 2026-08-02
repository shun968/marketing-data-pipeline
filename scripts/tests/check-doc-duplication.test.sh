#!/usr/bin/env bash
set -euo pipefail

# scripts/check-doc-duplication.sh の回帰テスト。
#
# この検査は誤検知するとレビュー無関係のコミットまで止める。
# 「検知すべき例」と同じ数だけ「検知してはいけない例」を置く。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-doc-duplication.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# 日本語の文字数はawkの実装(gawk=文字 / mawk=バイト)で変わる。
# どちらで数えても閾値をまたがない長さの文だけを使う
LONG='規約は1箇所にしか書かない。同じ内容が複数箇所にあると必ず更新漏れが起きて食い違う'
LONG2='収集データを外部へ出さない。一度pushした内容は履歴を書き換えても取り消しきれない'
SHORT='短い断片'

setup() {
  new_git_workdir
}

teardown() {
  cleanup_workdir
}

assert_exit() {
  assert_cmd_exit "$1" "$2" "${SCRIPT}"
}

echo "check-doc-duplication.sh"

# --- 検知すべきケース ---

setup
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > a.sh
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > b.sh
git add -A
assert_exit 1 "検知: 同じコメント行が2つのシェルスクリプトにある"
teardown

setup
printf '# 見出し\n\n%s\n' "${LONG}" > a.md
printf '# 別の見出し\n\n%s\n' "${LONG}" > b.md
git add -A
assert_exit 1 "検知: 同じ散文が2つのMarkdownにある"
teardown

# 規約の根拠がスクリプトのコメントとドキュメントの両方に書かれる形が実際に起きた
setup
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > a.sh
printf '# 見出し\n\n%s\n' "${LONG}" > b.md
git add -A
assert_exit 1 "検知: シェルのコメントとMarkdownの本文にまたがる"
teardown

# 強調やリスト記号を足しただけの写しを見逃すと、検査を足す意味が無い
setup
printf '# 見出し\n\n%s\n' "${LONG}" > a.md
printf '# 見出し\n\n- **%s**\n' "${LONG}" > b.md
git add -A
assert_exit 1 "検知: 強調・箇条書き記号の差を吸収する"
teardown

# --- 検知してはいけないケース ---

setup
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > a.sh
printf '#!/usr/bin/env bash\n# %s\n' "${LONG2}" > b.sh
git add -A
assert_exit 0 "誤検知しない: 別の文"
teardown

# 同じファイル内の繰り返しは「点在」ではない。弾くと定型コメントが書けなくなる
setup
printf '#!/usr/bin/env bash\n# %s\n# %s\n' "${LONG}" "${LONG}" > a.sh
git add -A
assert_exit 0 "誤検知しない: 同一ファイル内の繰り返し"
teardown

# コードの重複はテストの共通化などで別途扱う。ここで弾くと定型の代入が書けない
CODE_LINE='readonly EXPECTED_STATUS=0 ACTUAL_STATUS=0 RESULT_TEXT="" NAME_LABEL=""'
setup
printf '#!/usr/bin/env bash\n%s\n' "${CODE_LINE}" > a.sh
printf '#!/usr/bin/env bash\n%s\n' "${CODE_LINE}" > b.sh
git add -A
assert_exit 0 "誤検知しない: シェルのコード行"
teardown

# 表は語の並びが重複して当然。規約表を2つ書けなくなる
setup
printf '# 見出し\n\n| 対象 | 強制する仕組み | 規約の詳細 | 備考欄 | 補足事項 |\n' > a.md
printf '# 見出し\n\n| 対象 | 強制する仕組み | 規約の詳細 | 備考欄 | 補足事項 |\n' > b.md
git add -A
assert_exit 0 "誤検知しない: Markdownの表"
teardown

# 同じコマンド例を複数のドキュメントに載せられなくなる
FENCE='```'
CMD_LINE='uv run pytest && uv run ruff check . && uv run ruff format . && uv sync'
setup
printf '# 見出し\n\n%ssh\n%s\n%s\n' "${FENCE}" "${CMD_LINE}" "${FENCE}" > a.md
printf '# 見出し\n\n%ssh\n%s\n%s\n' "${FENCE}" "${CMD_LINE}" "${FENCE}" > b.md
git add -A
assert_exit 0 "誤検知しない: コードフェンス内"
teardown

setup
printf '#!/usr/bin/env bash\n# %s\n' "${SHORT}" > a.sh
printf '#!/usr/bin/env bash\n# %s\n' "${SHORT}" > b.sh
git add -A
assert_exit 0 "誤検知しない: 閾値未満の短い断片"
teardown

# 意図的に同じ文言を置く必要がある場合の逃げ道。無いと --no-verify を常用させる
setup
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > a.sh
printf '#!/usr/bin/env bash\n# %s dup-ok: 検査対象の見本\n' "${LONG}" > b.sh
git add -A
assert_exit 0 "誤検知しない: dup-ok マーカーのある行"
teardown

# 追跡外の下書きやスクラッチで無関係なコミットが止まってはいけない
setup
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > a.sh
git add a.sh
printf '#!/usr/bin/env bash\n# %s\n' "${LONG}" > b.sh
assert_exit 0 "誤検知しない: 未追跡ファイルは対象外"
teardown

# --- リポジトリ自身 ---

# 検査を足した本人が真っ先に違反する。実リポジトリで通ることを確かめる
actual=0
(cd "${REPO_ROOT}" && "${SCRIPT}") > /dev/null 2>&1 || actual=$?
check_exit 0 "このリポジトリ自身が重複を含まない" "${actual}"

suite_end
