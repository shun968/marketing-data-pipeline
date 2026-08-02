#!/usr/bin/env bash
set -euo pipefail

# scripts/check-adr-format.sh の回帰テスト。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-adr-format.sh"

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
  mkdir -p docs/adr scripts
  cp "${SCRIPT}" scripts/check-adr-format.sh
}

teardown() {
  cleanup_workdir
}

# write_adr <ファイル名> <ステータス行> <日付行> <本文>
write_adr() {
  {
    echo "# ADR-0009: 検証用の決定"
    echo ""
    echo "$2"
    echo "$3"
    echo ""
    echo "$4"
  } > "docs/adr/$1"
}

VALID_BODY='## コンテキスト

背景。

## 決定

**そうする。**

## 結果

結果。'

assert_exit() {
  assert_cmd_exit "$1" "$2" ./scripts/check-adr-format.sh "${@:3}"
}

echo "check-adr-format.sh"

# --- 通すべきケース ---

setup
write_adr "0009-valid-example.md" "- ステータス: 採用" "- 日付: 2026-08-01" "${VALID_BODY}"
assert_exit 0 "正しいADRを通す" docs/adr/0009-valid-example.md
teardown

setup
write_adr "0009-superseded.md" "- ステータス: 置換済み（ADR-0010）" "- 日付: 2026-08-01" "${VALID_BODY}"
assert_exit 0 "置換済み（ADR-XXXX）を通す" docs/adr/0009-superseded.md
teardown

setup
echo "# ADR一覧" > docs/adr/README.md
assert_exit 0 "README.mdは検査しない" docs/adr/README.md
teardown

setup
assert_exit 0 "ADR以外のパスは検査しない" CLAUDE.md
teardown

# コードフェンス内の `## ` は見出しではない。
# 除外しないとADR本文にMarkdownの例を書けなくなる
setup
write_adr "0009-with-fence.md" "- ステータス: 採用" "- 日付: 2026-08-01" '## コンテキスト

例を示す。

```markdown
## これは見出しではない
```

## 決定

**そうする。**

## 結果

結果。'
assert_exit 0 "コードフェンス内の見出しを誤検知しない" docs/adr/0009-with-fence.md
teardown

# --- 落とすべきケース ---

setup
write_adr "0009-caveat-status.md" "- ステータス: 採用（モデル選定は保留）" "- 日付: 2026-08-01" "${VALID_BODY}"
assert_exit 1 "ステータスの但し書きを検出する" docs/adr/0009-caveat-status.md
teardown

setup
write_adr "0009-unknown-status.md" "- ステータス: 検討中" "- 日付: 2026-08-01" "${VALID_BODY}"
assert_exit 1 "語彙外のステータスを検出する" docs/adr/0009-unknown-status.md
teardown

setup
write_adr "0009-bad-date.md" "- ステータス: 採用" "- 日付: 2026/08/01" "${VALID_BODY}"
assert_exit 1 "日付形式の違反を検出する" docs/adr/0009-bad-date.md
teardown

setup
write_adr "0009-old-headings.md" "- ステータス: 採用" "- 日付: 2026-08-01" '## 背景

背景。

## 決定

**そうする。**

## トレードオフ

不利益。'
assert_exit 1 "旧形式の見出しを検出する" docs/adr/0009-old-headings.md
teardown

setup
write_adr "0009-extra-heading.md" "- ステータス: 採用" "- 日付: 2026-08-01" '## コンテキスト

背景。

## 決定

**そうする。**

## 結果

結果。

## 補足

増やしてはいけない。'
assert_exit 1 "見出しの追加を検出する" docs/adr/0009-extra-heading.md
teardown

setup
write_adr "bad-name.md" "- ステータス: 採用" "- 日付: 2026-08-01" "${VALID_BODY}"
assert_exit 1 "命名違反を検出する" docs/adr/bad-name.md
teardown

setup
{
  echo "見出しが無い"
  echo ""
  echo "- ステータス: 採用"
  echo "- 日付: 2026-08-01"
  echo ""
  echo "${VALID_BODY}"
} > docs/adr/0009-no-title.md
assert_exit 1 "1行目のタイトル違反を検出する" docs/adr/0009-no-title.md
teardown

# --- 引数なし（stagedを自分で拾う）経路 ---
#
# pre-commitフックはこの経路で呼ばれるが、他の全ケースは明示的に
# ファイル引数を渡しているため、ここだけ検査されていなかった。
# gitの失敗を握り潰す形へ戻しても気づけない状態だった

setup
git init -q .
git config user.email test@example.com
git config user.name test
write_adr "0009-valid-example.md" "- ステータス: 採用" "- 日付: 2026-08-01" "${VALID_BODY}"
git add -A
assert_exit 0 "引数なし: stagedの正しいADRを通す"
teardown

setup
git init -q .
git config user.email test@example.com
git config user.name test
write_adr "0009-caveat.md" "- ステータス: 採用（保留あり）" "- 日付: 2026-08-01" "${VALID_BODY}"
git add -A
assert_exit 1 "引数なし: stagedの違反を検出する"
teardown

setup
git init -q .
git config user.email test@example.com
git config user.name test
write_adr "0009-unstaged.md" "- ステータス: 採用（保留あり）" "- 日付: 2026-08-01" "${VALID_BODY}"
assert_exit 0 "引数なし: stagedでないADRは対象外"
teardown

# gitが使えない場所では、対象0件で成功せずに中断する
setup
write_adr "0009-valid-example.md" "- ステータス: 採用" "- 日付: 2026-08-01" "${VALID_BODY}"
actual=0
./scripts/check-adr-format.sh > /dev/null 2>&1 || actual=$?
if [ "${actual}" -ne 0 ]; then
  echo "  ok   引数なし: gitリポジトリ外では失敗する（0件で成功しない）"
  passed=$((passed + 1))
else
  echo "  FAIL 引数なし: gitリポジトリ外では失敗する（0件で成功しない）"
  failed=$((failed + 1))
fi
teardown

suite_end
