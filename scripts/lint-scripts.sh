#!/usr/bin/env bash
set -euo pipefail

# シェルスクリプトとYAMLの静的検査。CIの guards ジョブと `task lint-scripts` の実体。
#
# なぜ必要か:
#   scripts/check-*.sh は「収集データを外部へ出さない」という最重要制約を守る
#   唯一の機構である。回帰テストは追加済みだが、未クォート変数や
#   `set -euo pipefail` 下での終了コード伝播といった静的な問題は、
#   テストが通っていても残る。
#   YAMLについては config/keywords.yaml の構文崩れが収集失敗に直結する。
#
# CIとローカルで実装を分けない:
#   同じ検査を2箇所に書くと、手元で通ったものがCIで落ちる。
#   CI(.github/workflows/ci.yml)はこのスクリプトを呼ぶだけにしてある。
#
# 検査対象を git ls-files で列挙する理由:
#   .venv や node_modules を除外でき、新しいディレクトリが増えても
#   追加作業なしで対象になる。
#   --others --exclude-standard を付けるのは、まだ `git add` していない
#   新規スクリプトを手元で検査対象に含めるため。CIには未追跡ファイルが無いので
#   結果は変わらない。

cd "$(git rev-parse --show-toplevel)"

# ubuntu-latest にはプリインストール版があるが、ランナー更新でバージョンが変わり
# 指摘が増減する。uvx(shellcheck-py)なら手元と同じ版で固定できる。
#
# 行頭を `# shellcheck` で始めないこと。ディレクティブとして解釈され
# SC1073 で落ちる（この検査を入れた最初のコミットで実際に踏んだ）
echo "==> shellcheck"
mapfile -t sh_files < <(git ls-files --cached --others --exclude-standard '*.sh')
if [ "${#sh_files[@]}" -gt 0 ]; then
  uvx --from shellcheck-py shellcheck "${sh_files[@]}"
  echo "  ${#sh_files[@]} ファイル: 指摘なし"
else
  echo "  対象なし"
fi

# --strict: warning も終了コードに反映させる。
# 体裁ルールは .yamllint.yml で無効化済みのため、ここで出る warning は
# キー重複など実害のあるものに限られる
echo "==> yamllint"
mapfile -t yaml_files < <(git ls-files --cached --others --exclude-standard '*.yml' '*.yaml')
if [ "${#yaml_files[@]}" -gt 0 ]; then
  uvx yamllint --strict "${yaml_files[@]}"
  echo "  ${#yaml_files[@]} ファイル: 指摘なし"
else
  echo "  対象なし"
fi
