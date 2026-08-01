#!/usr/bin/env bash
set -euo pipefail

# pre-commitフック用。収集データ・状態ファイル・生成レポート・APIキーが
# コミットへ混入していないかを検査し、見つかったらコミットを中断する。
#
# なぜ強制するか:
#   このリポジトリはPublicである。一度pushした内容はforce-pushで履歴を書き換えても
#   GitHub側にダングリングコミットとして残り、APIから参照できる場合がある。
#   事後の取り消しが効かないため、コミットの時点で止めるしかない。
#
# Claude Codeのhookではなくlefthookに置いている理由:
#   Claude Codeのhookはセッション内のツール実行にしか反応しない。
#   ターミナルから手動で `git add -A` した場合に素通りするため、
#   gitフック側でなければゲートとして成立しない。

# --diff-filter=ACMR: Added/Copied/Modified/Renamed のみ。
#                     Deleted を含めると、既に存在しないパスを検査対象にしてしまう
staged="$(git diff --cached --name-only --diff-filter=ACMR)"
[ -n "${staged}" ] || exit 0

violations=0

report() {
  # 値そのものは出力しない。ログや端末履歴に秘匿情報を残さないため、
  # 常に「どのファイルの何行目か」だけを示す
  echo "NG: $1" >&2
  violations=$((violations + 1))
}

# 1. 非公開ディレクトリ・環境ファイル
#    .gitignore済みだが、`git add -f` や .gitignore の編集で混入しうる
forbidden="$(echo "${staged}" | grep -E '^sns-collector/(data|state|reports)/|(^|/)\.env(\.|$)' || true)"
if [ -n "${forbidden}" ]; then
  while IFS= read -r f; do
    report "非公開ファイルがstagedにある: ${f}"
  done <<< "${forbidden}"
fi

# 2. .gitignore の対象がstagedに入っていないか
#    上のパターンに列挙し忘れた対象も、この汎用チェックで捕捉できる。
#    --no-index: 追跡済みかどうかに関わらず「無視ルールに合致するか」で判定する
#                (これが無いと、一度コミットされてしまったファイルを検出できない)
#    check-ignore は該当なしのとき終了コード1を返すため `|| true` が要る
ignored="$(echo "${staged}" | git check-ignore --stdin --no-index 2>/dev/null || true)"
if [ -n "${ignored}" ]; then
  while IFS= read -r f; do
    echo "${forbidden}" | grep -qxF "${f}" && continue
    report ".gitignore対象がstagedにある: ${f}"
  done <<< "${ignored}"
fi

# 3. 秘匿情報らしき文字列
#    このスクリプト自身が検出パターンを本文に含むため、除外しないと恒久的に自己検出する
scan_targets="$(echo "${staged}" | grep -vE '^scripts/check-' || true)"

# 各要素は "名称:正規表現"
patterns=(
  "Anthropic APIキー:sk-ant-[A-Za-z0-9_-]{20,}"
  "Google APIキー:AIza[0-9A-Za-z_-]{35}"
  "GitHubトークン:gh[pousr]_[A-Za-z0-9]{30,}"
  "秘密鍵:-----BEGIN [A-Z ]*PRIVATE KEY-----"
  "Blueskyアプリパスワード:[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}"
)

if [ -n "${scan_targets}" ]; then
  while IFS= read -r f; do
    # 作業ツリーではなくindexの内容を読む。
    # `git add` 後に作業ツリー側だけ修正されていても、実際にコミットされるのはindexの内容
    content="$(git show ":${f}" 2>/dev/null || true)"
    [ -n "${content}" ] || continue

    for entry in "${patterns[@]}"; do
      label="${entry%%:*}"
      regex="${entry#*:}"
      # -I: バイナリファイルをスキップする / -n: 行番号を出す
      # -e: パターンをオプションとして解釈させない
      #     (秘密鍵のパターンが `-----BEGIN` で始まり、無いとgrepがオプション扱いして失敗する)
      hits="$(echo "${content}" | grep -nIE -e "${regex}" | cut -d: -f1 || true)"
      [ -n "${hits}" ] || continue
      while IFS= read -r line_no; do
        report "${label}らしき文字列: ${f}:${line_no}"
      done <<< "${hits}"
    done
  done <<< "${scan_targets}"
fi

if [ "${violations}" -gt 0 ]; then
  cat >&2 <<'MSG'

コミットを中断した。収集データ・秘匿情報は外部へ出してはならない(CLAUDE.md)。

対処:
  git restore --staged <ファイル>     stagedから外す
  git rm --cached <ファイル>          追跡済みなら追跡を外す

意図的にコミットする必要がある場合は、なぜ安全かを確認したうえで
このスクリプトの検査対象を明示的に変更すること。--no-verify で迂回しない。
MSG
  exit 1
fi
