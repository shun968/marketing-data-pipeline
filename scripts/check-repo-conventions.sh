#!/usr/bin/env bash
set -euo pipefail

# 「規約が守られているか」ではなく「規約を守る仕組みが在るか」を検査する。
#
# なぜ必要か:
#   CLAUDE.mdに「検査スクリプトには回帰テストを足す」と書いてあったが、
#   lint-scripts.sh を追加したときに適用し忘れた。散文の規約は、その作業の
#   瞬間に想起されなければ発火しない。
#   同様に、テスト一覧を lefthook / ci.yml / Taskfile.yml の3箇所へ書いた結果、
#   テストを1本足したときに lefthook だけ更新が漏れた。
#
#   **規約を強く書くのではなく、規約を検査に変換する。**
#
# 使い方:
#   scripts/check-repo-conventions.sh
#
# テスト: scripts/tests/check-repo-conventions.test.sh

root="$(git rev-parse --show-toplevel)"
cd "${root}"

violations=0

report() {
  echo "NG: $1" >&2
  violations=$((violations + 1))
}

# 1. 検査スクリプトには回帰テストを伴わせる
#
#    対象は scripts/check-*.sh と scripts/lint-*.sh。
#    これらは「壊れても通常の開発では気づけない」種類のコードであり、
#    静かに0件を返すようになってもCIは緑のままになる。
#
#    列挙を作業ツリーではなくindexから行う理由:
#      作業ツリーを見ると、未追跡の一時スクリプト(scripts/check-tmp.sh 等)が
#      あるだけで無関係なコミットまで止まる。
#      逆にテスト側を作業ツリーで見ると、テストを `git add` し忘れたまま
#      検査スクリプトだけをコミットでき、素通りする。
#      index を唯一の参照にすれば、どちらも起きない。
index_file="$(mktemp)"
trap 'rm -f "${index_file}"' EXIT

if ! git ls-files -z > "${index_file}"; then
  echo "追跡ファイルの一覧を取得できなかったため中断する" >&2
  exit 1
fi
mapfile -d '' -t tracked < "${index_file}"

in_index() {
  local target="$1" entry
  for entry in "${tracked[@]-}"; do
    [ "${entry}" = "${target}" ] && return 0
  done
  return 1
}

# 作業ツリーではなくindexの内容を読む。
# 参照先が検査ごとに違うと、未stagedの編集で無関係なコミットが止まったり、
# stagedの違反を作業ツリーで戻すだけで素通りしたりする。
# **この検査はすべてindexだけを見る**
index_content() {
  git show ":$1"
}

for script in "${tracked[@]-}"; do
  case "${script}" in
    scripts/check-*.sh | scripts/lint-*.sh) ;;
    *) continue ;;
  esac
  name="$(basename "${script}" .sh)"
  test_file="scripts/tests/${name}.test.sh"
  in_index "${test_file}" || report "${script} に対応するテストが無い（${test_file} を作る）"
done

# 2. テスト一覧を複数箇所へ書かない
#
#    lefthook / CI / Taskfile が個々のテストを直接列挙すると、
#    テストを足したときにどれかが漏れる。すべて run-all.sh を呼ぶ。
#    検出するのは「実際の呼び出し」だけにする。`./scripts/tests/<名前>.test.sh`
#    の形に限定し、説明文中の `scripts/tests/*.test.sh` のようなグロブ表記は
#    対象外にする(誤検知はゲートの迂回を招く)
INVOCATION='\./scripts/tests/[A-Za-z0-9_-]+\.test\.sh'
for caller in lefthook.yml .github/workflows/ci.yml Taskfile.yml; do
  in_index "${caller}" || continue
  if index_content "${caller}" | grep -qE -- "${INVOCATION}"; then
    report "${caller} がテストを直接列挙している（scripts/tests/run-all.sh を呼ぶ）"
  fi
done

# 3. run-all.sh は列挙ではなく検出でテストを集める
#
#    ここに個々のテスト名が書かれていると、1と2を満たしていても
#    結局は列挙の更新漏れが起きる
if in_index scripts/tests/run-all.sh; then
  # グロブ(`*.test.sh`)は許可し、具体名(`foo.test.sh`)だけを弾く。
  # `.test.sh` の直前が英数字かどうかで区別する
  if index_content scripts/tests/run-all.sh | grep -qE '^[^#]*[A-Za-z0-9_-]\.test\.sh'; then
    report "scripts/tests/run-all.sh がテスト名を直接列挙している（*.test.sh の検出にする）"
  fi
fi

if [ "${violations}" -gt 0 ]; then
  echo "" >&2
  echo "規約を守る仕組みが欠けている。背景は scripts/check-repo-conventions.sh の先頭コメントを参照する。" >&2
  exit 1
fi
