# CLAUDE.md

SNS上の投稿から市場の潜在的な顧客要望・製品優位性を継続的に収集・構造化し、個人開発の事業仮説を立てるためのローカル分析基盤。

設計の全体像は `docs/` を参照する（`docs/README.md` が索引）。

## 最重要ルール

### 収集データを外部へ出さない

```
sns-collector/data/     収集した生データ・DB     ← 絶対にコミットしない
sns-collector/state/    SeenStore・ログ・ロック   ← 絶対にコミットしない
sns-collector/reports/  生成レポート             ← 絶対にコミットしない
sns-collector/.env      APIキー                  ← 絶対にコミットしない
```

すべて `.gitignore` 済みだが、**このリポジトリはPublicである**。`git add -A` や `git add .` を使う際は、これらが含まれていないことを必ず確認する。

埋め込み生成はローカルモデルで行い、外部APIへ投稿本文を送信しない（ADR-0002）。唯一の例外は構造化抽出で、Claude Codeセッション経由で投稿本文がAnthropicへ送信される（ADR-0003）。この線引きを勝手に動かさない。

### パイプラインからLLM APIを呼ばない

構造化抽出はバッチファイルの受け渡しでClaude Codeセッションが担う。`sns-collector` のコードにLLM API呼び出しを追加しない。これは追加課金を発生させないための構造的な制約である（ADR-0003）。

## リポジトリ構成

```
docs/                   設計ドキュメント（requirements / design / roadmap / adr）
sns-collector/          収集ツール（Python 3.11+ / uv）
  config/               keywords.yaml（検索語） domains.yaml（観測ドメインと仮説）
  src/sns_collector/
    common/http.py      全HTTPリクエストの仲介。ペーシングと再試行
    common/config.py    設定ロード
    common/seen_store.py  重複排除（Phase 1でDBへ統合予定）
    bluesky/ youtube/   プラットフォーム別のclient/search/models
  tests/                単体テストのみ。実API通信は行わない
Taskfile.yml            開発タスク（lint / GitHub設定）
```

## 開発コマンド

```sh
cd sns-collector
uv sync                     # 依存インストール
uv run pytest               # テスト
uv run ruff check .         # lint
uv run ruff format .        # フォーマット
uv run sns-collector bluesky   # 収集（手動実行）
uv run sns-collector youtube
```

cronで3時間おきに自動収集される（`scripts/cron_run.sh`）。

## 規約

### コード

- Python 3.11以上。`from __future__ import annotations` を先頭に置く
- ruff: line-length 100、select は `E, F, I, UP`
- 型ヒントを付ける。dataclassは `frozen=True` を既定とする
- コメント・docstring・ログ出力は日本語で書く（既存コードに合わせる）
- コメントは「コードが示せない制約」を書く時だけ。次の行が何をするかの説明は書かない

### コミット

commitlint（`@commitlint/config-conventional`）が以下を強制する。

- **body・footerは空にすること**。`Co-Authored-By` 等のトレーラーは付けられない
- **issue参照が必須**。件名末尾に `(#3)` の形式で入れる
- 型は `feat` / `fix` / `docs` / `chore` / `test` / `refactor` など

```
feat(sns-collector): redefine keyword strategy for demand signals (#3)
```

### テスト

- **実際のAPI通信を行わない。** `requests` またはその上位関数をモックする
- 新しい失敗モードを修正したら、必ず回帰テストを追加する
- 冪等性は「同じ入力で2回実行して結果が変わらない」ことをテストで担保する

## 踏んだ罠（再発防止）

### 収集の途中失敗で全件を失った

保存が全キーワード完了後の一括のみだったため、11キーワード目の403で先行201件が破棄された。現在はキーワード単位で例外を捕捉して続行する。

**ループで収集して最後にまとめて保存する形を新たに書かない。** 途中失敗で何が失われるかを必ず確認する。

### キーワード設計の2原則

`config/keywords.yaml` の改訂時は必ず守る。詳細と実測データは `sns-collector/README.md`。

1. **固有名詞・技術用語のアンカーを必ず含める。** 日本語には語境界がなく、一般語だけの組み合わせはノイズに埋もれる（`量子化 精度` → 中国語の量子化学）
2. **英字の固有名詞には日本語の語を添える。** 英字のみは英語圏・公式アカウント・botを拾う（`OpenVINO` → GitHubトレンドbot）

同名衝突がある語には限定語を添える（`パラレルリンク` → 遊戯王のカード）。キーワードを変更したら実データをサンプリングして質を確認し、改訂履歴に根拠を残す。

## レビュー観点

`/code-review --comment` でPRをレビューする際、この4点を優先する。

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
