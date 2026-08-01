#!/usr/bin/env bash
set -euo pipefail

# scripts/check-adr-format.sh の回帰テスト。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/check-adr-format.sh"

passed=0
failed=0
workdir=""

setup() {
  workdir="$(mktemp -d)"
  cd "${workdir}"
  mkdir -p docs/adr scripts
  cp "${SCRIPT}" scripts/check-adr-format.sh
}

teardown() {
  cd /
  [ -n "${workdir}" ] && rm -rf "${workdir}"
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

# assert_exit <期待する終了コード> <ケース名> <検査対象...>
assert_exit() {
  local expected="$1" name="$2" actual=0
  shift 2
  ./scripts/check-adr-format.sh "$@" > /dev/null 2>&1 || actual=$?
  if [ "${actual}" -eq "${expected}" ]; then
    echo "  ok   ${name}"
    passed=$((passed + 1))
  else
    echo "  FAIL ${name}（期待: ${expected} / 実際: ${actual}）"
    failed=$((failed + 1))
  fi
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

echo "  ---"
echo "  成功 ${passed} / 失敗 ${failed}"
[ "${failed}" -eq 0 ]
