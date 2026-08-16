#!/usr/bin/env bash
set -euo pipefail

# APIキーを持つ環境ファイルが、ワークスペースの内側に置かれていないかを検査する。
#
# なぜ必要か:
#   ワークスペースはdevcontainerへbindマウントされる。Claude Codeの
#   permissions deny(Read/Edit)はツール層の制御点でしかなく、Bashが起動した
#   子プロセス(python 等)がファイルを開くのは止められない
#   (docs/isolation.md §3 経路3)。この機械ではBashサンドボックスが起動できない
#   ため(ADR-0007)、経路3を塞ぐOS層が無い。
#   **鍵を境界の内側に置かないことが、この経路に対する唯一の対処である**(ADR-0012)。
#
#   .gitignore と check-no-private-data.sh は「コミットへの混入」を止めるが、
#   混入しなくてもファイルがそこに在るだけでセッションから読める。
#   止めたい状態が違うため、検査も別にする。
#
# CIのジョブに入れていない理由:
#   CIはクリーンなチェックアウトで走り、環境ファイルはそもそも存在しない。
#   常に0件で緑になる検査をジョブへ足すと、「見ているつもり」の枠が増える。
#   この検査が見ているのは開発者の作業環境の状態であり、pre-commitで足りる。
#
# 使い方:
#   scripts/check-secret-outside-workspace.sh
#
# テスト: scripts/tests/check-secret-outside-workspace.test.sh

root="$(git rev-parse --show-toplevel)"
cd "${root}"

violations=0

# report <ルールID> <詳細>。IDの決め方は scripts/record-check.sh を参照  dup-ok: 関数シグネチャの案内
report() {
  echo "NG: [$1] $2" >&2
  violations=$((violations + 1))
}

# -print0 と mapfile -d '' で受ける。非ASCIIのディレクトリ名があっても
# 分割位置がずれない(check-shell-idioms.sh の git-list-without-z と同じ理由)。
#
# .env.example / .env.sample はキーを含まないテンプレートであり、追跡が前提。
# 実キーが書かれた場合は check-no-private-data.sh の「秘匿情報らしき文字列」が捕捉する。
found_file="$(mktemp)"
trap 'rm -f "${found_file}"' EXIT

if ! find . \
  \( -name .git -o -name .venv -o -name node_modules -o -name __pycache__ \) -prune \
  -o \( -name '.env' -o -name '.env.*' \) \
  ! -name '.env.example' ! -name '.env.sample' \
  -type f -print0 > "${found_file}"; then
  echo "環境ファイルの探索に失敗したため中断する。0件として通すと検査が素通りする。" >&2
  exit 1
fi

mapfile -d '' -t found < "${found_file}"
for f in "${found[@]-}"; do
  [ -n "${f}" ] || continue
  report secret-in-workspace "環境ファイルがワークスペース内にある: ${f#./}"
done

if [ "${violations}" -gt 0 ]; then
  cat >&2 <<'MSG'

鍵はワークスペースの外へ置く(ADR-0012)。境界の内側に在ると、セッションの
子プロセスから読め、内容がモデルの文脈へ載る経路が開いたままになる。

対処(ホスト側で行う。パスは cron_run.sh の既定値):
  mkdir -p ~/.config/sns-collector
  mv sns-collector/.env ~/.config/sns-collector/.env
  chmod 600 ~/.config/sns-collector/.env

置き場所を変える場合は SNS_COLLECTOR_ENV_FILE で指す。
MSG
  exit 1
fi
