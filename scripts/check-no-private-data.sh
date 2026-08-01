#!/usr/bin/env bash
set -euo pipefail

# 収集データ・状態ファイル・生成レポート・APIキーがコミットへ混入していないかを
# 検査し、見つかったら中断する。
#
# 使い方:
#   scripts/check-no-private-data.sh                 staged を検査する(pre-commit用・既定)
#   scripts/check-no-private-data.sh --range A...B   範囲の変更ファイルを検査する(CI用)
#   scripts/check-no-private-data.sh --all           追跡中の全ファイルを検査する
#
# CI用モードが要る理由:
#   CIにはステージング領域が無い。既定のまま実行すると対象が常に0件になり、
#   「通っているのに何も見ていない」状態になる。
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
#
# 誤検知を出さないこと自体が要件である:
#   CLAUDE.mdで「--no-verify で迂回しない」と定めている以上、
#   正常なコミットが止まる状態を放置すると迂回が常態化し、ゲートが無意味になる。
#   検出パターンを足すときは、必ず scripts/tests/ に誤検知しないケースを追加する。
#
# テスト: scripts/tests/check-no-private-data.test.sh

MODE="staged"
RANGE=""
RANGE_HEAD="HEAD"
case "${1-}" in
  "") ;;
  --all) MODE="all" ;;
  --range)
    MODE="range"
    RANGE="${2-}"
    case "${RANGE}" in
      "" | -*) echo "usage: $0 --range <base>...<head>" >&2; exit 2 ;;
    esac
    # 内容は範囲のhead側から読む。HEAD固定にすると、チェックアウト位置が
    # 範囲headと異なる場合に git show が失敗し、空文字として黙って
    # 検査対象から外れる(=漏洩を見逃す)。
    # "A...B" / "A..B" のどちらでも B を取り出す。B省略時はHEAD
    RANGE_HEAD="${RANGE##*..}"
    [ -n "${RANGE_HEAD}" ] || RANGE_HEAD="HEAD"
    ;;
  *) echo "usage: $0 [--range <base>...<head> | --all]" >&2; exit 2 ;;
esac

# -z: パスをNUL区切り・エスケープなしで出力する。
#     既定(core.quotePath=true)では非ASCIIパスが "\346\212\225..." 形式へ
#     クォートされ、`git show` が失敗して黙って検査対象から外れる。
#     日本語のファイル名を使う可能性がある以上、-z でなければ検出漏れになる。
# --diff-filter=ACMR: Added/Copied/Modified/Renamed のみ。
#     Deleted を含めると、既に存在しないパスを検査対象にしてしまう
# 一時ファイルを経由するのは、gitの終了ステータスを捨てないため。
# `mapfile < <(git ...)` はプロセス置換であり set -e の対象外になる。
# 解決できない範囲を渡すと git は fatal を出して何も書かないが、
# 配列が空になるだけでスクリプトは 0 で終了する。
# = ゲートが緑になって0件しか見ていない状態になり、このモードの意味が消える。
filelist="$(mktemp)"
trap 'rm -f "${filelist}"' EXIT

collect_files() {
  case "${MODE}" in
    staged) git diff --cached --name-only -z --diff-filter=ACMR ;;
    range)  git diff --name-only -z --diff-filter=ACMR "${RANGE}" ;;
    all)    git ls-files -z ;;
  esac
}

if ! collect_files > "${filelist}"; then
  {
    echo ""
    echo "検査対象のファイル一覧を取得できなかった (mode=${MODE}${RANGE:+, range=${RANGE}})。"
    echo "対象を特定できないまま通すと検査が素通りするため中断する。"
    echo ""
    echo "CIで --range が解決できない場合、次を疑うこと:"
    echo "  - actions/checkout の fetch-depth が浅く、base のコミットが取得できていない"
    echo "  - base ブランチが force-push / rebase され、base.sha が到達不能になった"
  } >&2
  exit 1
fi

mapfile -d '' -t staged < "${filelist}"
[ "${#staged[@]}" -gt 0 ] || exit 0

# 内容をどの参照から読むか。ファイル一覧の取得元と揃える必要がある。
#   staged / all : index("")。`git add` 後に作業ツリー側だけ修正されていても、
#                  実際にコミットされるのはindexの内容であるため。
#                  all は git ls-files がindexを列挙するので同じ参照になる。
#   range        : 範囲のhead側。
REF=""
[ "${MODE}" = "range" ] && REF="${RANGE_HEAD}"

violations=0

report() {
  # 値そのものは出力しない。ログや端末履歴に秘匿情報を残さないため、
  # 常に「どのファイルの何行目か」だけを示す
  echo "NG: $1" >&2
  violations=$((violations + 1))
}

# 1. 非公開ディレクトリ・環境ファイル
#    .gitignore済みだが、`git add -f` や .gitignore の編集で混入しうる
forbidden=()
for f in "${staged[@]}"; do
  # 順序が意味を持つ。
  # 1) 非公開ディレクトリを最初に判定する。case の * は / にもマッチするため、
  #    許可リストを先に置くと sns-collector/data/.env.example が
  #    */.env.example にマッチして検査をすり抜ける。
  # 2) 次に .env.example / .env.sample を許可する。キーを含まないテンプレートで
  #    追跡が前提。実キーが書かれた場合は下の「秘匿情報らしき文字列」検査で捕捉する。
  # 3) 最後に .env 系を禁止する。
  case "${f}" in
    sns-collector/data/* | sns-collector/state/* | sns-collector/reports/*) ;;
    .env.example | .env.sample | */.env.example | */.env.sample) continue ;;
    .env | .env.* | */.env | */.env.*) ;;
    *) continue ;;
  esac
  forbidden+=("${f}")
  report "非公開ファイルが含まれている: ${f}"
done

# 2. .gitignore の対象がstagedに入っていないか
#    上のパターンに列挙し忘れた対象も、この汎用チェックで捕捉できる。
#    --no-index: 追跡済みかどうかに関わらず「無視ルールに合致するか」で判定する
#                (これが無いと、一度コミットされてしまったファイルを検出できない)
#    check-ignore は該当なしのとき終了コード1を返すため `|| true` が要る
mapfile -d '' -t ignored < <(
  printf '%s\0' "${staged[@]}" | git check-ignore -z --stdin --no-index 2>/dev/null || true
)
for f in "${ignored[@]}"; do
  duplicate=0
  for g in "${forbidden[@]-}"; do
    [ "${g}" = "${f}" ] && { duplicate=1; break; }
  done
  [ "${duplicate}" -eq 1 ] && continue
  report ".gitignore対象が含まれている: ${f}"
done

# 3. 秘匿情報らしき文字列
#    このスクリプト自身は検出パターンを本文に含むため、除外しないと恒久的に自己検出する。
#    除外はこの1ファイルに限定する。`scripts/check-*` のような前方一致で除外すると、
#    将来追加するスクリプトが気づかないうちにスキャン対象外になる。
#    テストは秘匿情報を実行時に組み立てるため、除外しなくても自己検出しない。
SELF="scripts/check-no-private-data.sh"

# 各要素は "名称:正規表現"
#
# Blueskyアプリパスワードの前後に `[^0-9a-z-]` を要求しているのは、
# 小文字UUID(`123e4567-e89b-12d3-a456-426614174000`)の内部に
# 4-4-4-4 が必ず現れ、誤検知でコミットが止まるため。
patterns=(
  "Anthropic APIキー:sk-ant-[A-Za-z0-9_-]{20,}"
  "Google APIキー:AIza[0-9A-Za-z_-]{35}"
  "GitHubトークン:gh[pousr]_[A-Za-z0-9]{30,}"
  "秘密鍵:-----BEGIN [A-Z ]*PRIVATE KEY-----"
  "Blueskyアプリパスワード:(^|[^0-9a-z-])[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}([^0-9a-z-]|$)"
)

for f in "${staged[@]}"; do
  [ "${f}" = "${SELF}" ] && continue

  # 読めなかったものを黙って飛ばさない。
  # 空文字として扱うと、参照の指定ミスで検査対象から外れたことに気づけず、
  # 「通っているのに何も見ていない」状態を作る。fail-closed にする。
  if ! git cat-file -e "${REF}:${f}" 2>/dev/null; then
    report "内容を読めなかった(参照: ${REF:-index}): ${f}"
    continue
  fi
  content="$(git show "${REF}:${f}" 2>/dev/null || true)"
  # 空ファイルはここで正常にスキップされる(上で存在は確認済み)
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
done

if [ "${violations}" -gt 0 ]; then
  cat >&2 <<'MSG'

収集データ・秘匿情報は外部へ出してはならない(CLAUDE.md)。

対処:
  git restore --staged <ファイル>     stagedから外す
  git rm --cached <ファイル>          追跡済みなら追跡を外す

誤検知だと判断した場合は、--no-verify で迂回せず、検出パターンを修正して
scripts/tests/ に「検知してはいけないケース」としてテストを追加すること。

既にpush済みの場合、force-pushで履歴を書き換えてもGitHub側にダングリング
コミットとして残る。APIキーは必ず失効させ、再発行すること。
MSG
  exit 1
fi
