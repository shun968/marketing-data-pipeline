# CLAUDE.md

SNS上の投稿から市場の潜在的な顧客要望・製品優位性を継続的に収集・構造化し、個人開発の事業仮説を立てるためのローカル分析基盤。

設計の全体像は `docs/design.md` を参照する（冒頭から requirements / roadmap / adr へ辿れる）。技術選定の判断根拠は `docs/adr/` にある。

## 最重要ルール

### 収集データを外部へ出さない

```
sns-collector/data/     収集した生データ・DB     ← 絶対にコミットしない
sns-collector/state/    SeenStore・ログ・ロック   ← 絶対にコミットしない
sns-collector/reports/  生成レポート             ← 絶対にコミットしない
sns-collector/.env      APIキー                  ← 絶対にコミットしない
.metrics/               ガードレール抵触の記録     ← 絶対にコミットしない
```

すべて `.gitignore` 済みだが、**このリポジトリはPublicである**。`git add -A` や `git add .` を使う際は、これらが含まれていないことを必ず確認する。

これは `scripts/check-no-private-data.sh` が pre-commit（lefthook）で機械的に検査する。**`--no-verify` で迂回しない。** 一度pushした内容は履歴を書き換えても取り消しきれない。

埋め込み生成はローカルモデルで行い、外部APIへ投稿本文を送信しない（ADR-0002）。唯一の例外は構造化抽出で、Claude Codeセッション経由で投稿本文がAnthropicへ送信される（ADR-0003）。この線引きを勝手に動かさない。

### パイプラインからLLM APIを呼ばない

構造化抽出はバッチファイルの受け渡しでClaude Codeセッションが担う。`sns-collector` のコードにLLM API呼び出しを追加しない。これは追加課金を発生させないための構造的な制約である（ADR-0003）。

## リポジトリ構成

```
.claude/skills/           作業手順（adr など）。該当作業に入ったら従う
docs/                     設計ドキュメント（requirements / design / roadmap / adr）
scripts/                  リポジトリ共通スクリプト（規約チェック / lint / コミットメッセージ補助）
  check-no-private-data.sh  収集データ・秘匿情報の混入検査（pre-commit）
  check-adr-format.sh       ADRの書式検査（pre-commit）
  check-shell-idioms.sh     過去に事故を起こしたシェルの書き方を検出（pre-commit / CI）
  check-repo-conventions.sh 規約を守る仕組みが在るかの検査（pre-commit / CI）
  check-doc-duplication.sh  規約の書き写しの検出（pre-commit / CI）
  check-rule-consolidation.sh 統合整理の確認。人へ聞く（pre-commit のみ）
  record-check.sh           検査の実行記録。ガードレール見直しの入力（pre-commit）
  lint-scripts.sh           シェル・YAMLの静的検査（pre-commit / CI）
  tests/                    検査スクリプトの回帰テスト。`task test-check-scripts`
    lib.sh                  各テストの共通処理（setup / 集計 / アサーション）
lefthook.yml              gitフックの登録。規約の強制はここに集約する
.metrics/                 ガードレール抵触の記録（ローカル計測）  ← コミットしない
dashboard/                モニタリング画面（Python 3.11+ / uv）
  CLAUDE.md               ← この領域の規約・開発コマンドはこちら
sns-collector/            収集ツール（Python 3.11+ / uv）
  CLAUDE.md               ← この領域の規約・開発コマンドはこちら
  config/                 keywords.yaml（検索語） domains.yaml（観測ドメインと仮説）
  scripts/cron_run.sh     定期収集のcronラッパー（flockによる多重起動防止）
  src/sns_collector/
    common/http.py        全HTTPリクエストの仲介。ペーシングと再試行
    common/config.py      設定ロード
    common/seen_store.py  重複排除（Phase 1でDBへ統合予定）
    bluesky/ youtube/     プラットフォーム別のclient/search/models
  tests/                  単体テストのみ。実API通信は行わない
Taskfile.yml              開発タスク（lint / GitHub設定）
```

領域固有の規約は各ディレクトリの `CLAUDE.md` に置く。ルートには**どこにでも適用される命令だけ**を置き、特定のスタック・領域に閉じたものは持ち込まない。

## 規約

**規約は1箇所にしか書かない。機械的に検査できるものは仕組みを正とし、ドキュメントには「何がどこで強制されるか」だけを置く。** 同じ内容が複数箇所にあると、必ず更新漏れが起きて食い違う。

| 対象 | 強制する仕組み | 規約の詳細 |
|---|---|---|
| 収集データ・秘匿情報の混入 | lefthook pre-commit と `git add` 直後のhook → `scripts/check-no-private-data.sh` | 上の「最重要ルール」 |
| ADRの書式・ステータス | lefthook pre-commit と編集直後のhook → `scripts/check-adr-format.sh` | `adr` スキル |
| コミットメッセージ | lefthook commit-msg → commitlint | `commitlint.config.js` |
| Pythonのlint・フォーマット | ruff（CI `sns-collector`） | `sns-collector/pyproject.toml` |
| シェル・YAMLの静的検査 | lefthook pre-commit と CI `guards` → `scripts/lint-scripts.sh` | shellcheck / `.yamllint.yml` |
| 過去に事故を起こしたシェルの書き方 | 同上 → `scripts/check-shell-idioms.sh` | 同スクリプトの先頭コメント |
| 検査スクリプトのテスト同伴・列挙の重複 | lefthook pre-commit と CI `guards` → `scripts/check-repo-conventions.sh` | 同スクリプトの先頭コメント |
| 規約の書き写し | lefthook pre-commit と CI `guards` → `scripts/check-doc-duplication.sh` | 同スクリプトの先頭コメント |
| 規約を足したときの統合整理 | lefthook pre-commit の承認フロー → `scripts/check-rule-consolidation.sh` | 同スクリプトの先頭コメント |
| 違反出力のルールID・検査の記録漏れ | lefthook pre-commit と CI `guards` → `scripts/check-repo-conventions.sh` | `scripts/record-check.sh` の先頭コメント |

- 領域固有の規約は各ディレクトリの `CLAUDE.md` に置く（例: `sns-collector/CLAUDE.md`）
- 作業手順は `.claude/skills/` に置く。該当する作業に入ったらスキルに従う
- **検査を追加したらこの表に行を足し、ドキュメント側の重複記述を消す**
- 検査スクリプトを変更したら `scripts/tests/` に回帰テストを足す。**「検知できること」と同じ重みで「誤検知しないこと」をテストする。** 誤検知は `--no-verify` の常用を招き、ゲートを無効化する

### 機械検査と承認フローの使い分け

判定に意図が要るものを正規表現で近似すると、誤検知が増えてゲートごと無効化される。**文字列で判定できるものは検査に、できないものは人への確認に落とす。**

| | 機械検査 | 承認フロー |
|---|---|---|
| 判定 | 文字列・構造で決まる | 意図を読む必要がある |
| 例 | 同じ文が2ファイルにある | この規約は既存のどれかに畳めるか |
| 失敗の形 | 誤検知で無関係なコミットが止まる | 質問が多すぎて反射的に承認される |

承認フローは**発火条件を絞ることが要件**である。何にでも掛けると承認が形骸化し、機械検査より弱くなる。追加する際は、聞かないケースを聞くケースと同じ数だけテストに書く。

### Pythonの書き方

`sns-collector` と `dashboard` の両方に適用する。領域固有のものは各 `CLAUDE.md` に置く。

- Python 3.11以上。`from __future__ import annotations` を先頭に置く
- lint・フォーマットは ruff に従う（設定は各 `pyproject.toml`。ここには書き写さない）
- 型ヒントを付ける。dataclassは `frozen=True` を既定とする
- コメント・docstringは日本語で書く
- コメントは「コードが示せない制約」を書く時だけ。次の行が何をするかの説明は書かない

コミットメッセージの形（body・footerは空、件名末尾にissue参照）:

```
feat(sns-collector): redefine keyword strategy for demand signals (#3)
```

## モニタリング

`task dashboard` で http://127.0.0.1:8787 に画面が立つ。開発ルール・ADR・レポート・ガードレールメトリクスを1画面で見る。詳細は `dashboard/CLAUDE.md`。

**この画面は収集データをそのまま表示する。127.0.0.1 から動かさない。**

ガードレールメトリクスは pre-commit の実行時に `scripts/record-check.sh` が記録する。用途は**ルールの見直し**であり、次の判断に使う。

- 一度も発火していない検査 → 剥がす候補。ゲートは増やすほど遅くなり、遅い pre-commit は `--no-verify` の常用を招く
- 繰り返し発火するルール → 検査で止めるのではなく、設計で潰す候補

**画面は候補を挙げるだけで、要不要は断定しない。** 発火していない検査が抑止力として効いている場合があるため、判断は人が行う。

## CI

`.github/workflows/ci.yml` がPRとmainへのpushで走り、rulesetの `required_status_checks` によりマージ条件になっている。

| ジョブ | 内容 |
|---|---|
| `guards` | シェル・YAMLの静的検査 / 禁止イディオム / リポジトリ規約 / 規約の書き写し / 検査スクリプトの回帰テスト / 収集データ・秘匿情報の混入検査 / ADR書式 |
| `sns-collector` | ruff check / ruff format --check / pytest |
| `dashboard` | ruff check / ruff format --check / pytest |

レビューは `.github/workflows/claude-review.yml` が別ワークフローで走らせる（下記「レビュー」）。**このジョブを `required_status_checks` に入れない。** 上限到達によるスキップがそのままマージ不能になる。

**CIとローカルで検査の実装を分けない。** CIのステップはローカルと同じスクリプトを呼ぶだけにする。同じ検査を2箇所に書くと、手元で通ったものがCIで落ちる。

**CIにはステージング領域が無い。** `check-no-private-data.sh` を既定モードのままCIで実行すると対象が常に0件になり、通っているのに何も見ていない状態になる。PRでは `--range <base>...HEAD`、mainへのpushでは `--all` を渡す。

ジョブ名は `Taskfile.yml` の `required_status_checks` の `context` と一致させること。ここがずれるとチェックが永久にpendingになり、マージできなくなる。

## レビュー

**PR作成・更新のたびに `.github/workflows/claude-review.yml` がヘッドレスでレビューを走らせる。** 認証はサブスクリプションのOAuthトークン（secret `CLAUDE_CODE_OAUTH_TOKEN`、`claude setup-token` で発行）で、モデルは `--model opus` を指定している。

rulesetの `required_review_thread_resolution` は「未解決コメントがあるPR」しか止められない。レビューを走らせなければコメントはゼロで素通りするため、実行そのものをイベント駆動にしてある。

**レビューが走らない条件はいくつもある**（付与分の超過、トークンの失効、ワークフロー自体を変更したPR）。ワークフローは終了状態ではなく**実行された形跡の有無**で判定し、走らなかった場合はその旨をPRへコメントする。コメントが付いていたら、マージ前に手元のセッションで `/code-review <PR番号> --comment` を実行すること。この最後の一手だけは運用で担保するしかない。

### 指摘を閉じる条件

**「直した」だけでは指摘を閉じない。** 指摘ごとに次のいずれかを行う。

1. 機械検査を追加する（`scripts/check-shell-idioms.sh` にルールを足す、など）
2. スキルに追記する
3. **機械化できない理由をコードのコメントに残す**

同じ指摘が別のファイルで繰り返し発生している。非ASCIIパスの `-z` 漏れは3つのスクリプトで、テストの同伴漏れは2回起きた。**修正だけでは次のファイルで再発する。**

規約を散文で強く書いても、その作業の瞬間に想起されなければ発火しない。**規約を強くするのではなく、規約を検査に変換する。**

### 観点

レビューではこの4点を優先する。

### 1. データ整合性

- 冪等性は保たれるか（同じ入力の再実行で結果が変わらないか）
- 重複排除が機能するか
- **処理の途中で失敗したとき、収集済み・処理済みのデータが失われる経路がないか**
- 生データ（JSONL）を失う変更が含まれていないか

### 2. 秘匿情報の混入

- 収集データ・APIキー・個人を特定しうる情報がコミットに含まれていないか
- `.gitignore` の対象がコミットに紛れ込んでいないか
- ログ出力に投稿本文やキーが混ざっていないか

### 3. スキーマ影響

- DBスキーマ変更に対して移行手順があるか
- 既存データと非互換になっていないか
- `config/domains.yaml` の統制語彙と抽出結果の整合が取れているか

### 4. テスト

- 新しい失敗モードに対する回帰テストがあるか
- モックが実API通信を確実に防いでいるか
- 冪等性が担保されているか

**スタイルや命名の指摘は上記4点より優先度を下げる。** lintで機械的に防げるものはレビューで指摘せず、ruffのルールとして追加することを提案する。
