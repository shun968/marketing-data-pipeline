# 分析基盤 設計

最終更新: 2026-07-28

関連: [requirements.md](./requirements.md) / [roadmap.md](./roadmap.md) / [adr/](./adr/)

---

## 1. 設計方針

### 1.1 一度だけ推論し、結果を凍結する

本基盤の中核となる原則である。

投稿本文は自然言語であり、そのままでは検索も集計もできない。かといって検索のたびにLLMへ解釈させると、コスト・再現性・応答時間のすべてで破綻する。

そこで、**取り込み時に一度だけ構造化抽出を行い、その結果を確定値としてDBへ書き込む**。以降の検索・集計・レポート生成は、この確定値に対する決定論的な処理として実行する。推論が発生する箇所を取り込み時の1点に限定することで、下流の全処理が検証可能になる。

```
生投稿（自然言語・解釈が必要）
   ↓ ［推論はここだけ］
構造化された洞察（確定値・以降は事実として扱う）
   ↓ ［決定論的処理］
検索 / 集計 / レポート
```

### 1.2 パイプライン本体はLLMに依存しない

構造化抽出はClaude Codeセッションが担い、パイプラインのコードは「バッチを書き出す」「結果を検証して取り込む」だけを行う。この分離により、

- パイプラインはLLM APIキーなしで動作し、追加課金が発生しない（N-04）
- 抽出以外の全処理が通常の単体テストで検証できる
- 将来ローカルLLMやAPIへ切り替える場合も、バッチの入出力形式を守れば実装差し替えで済む

### 1.3 生データを捨てない

`data/{platform}/<日付>.jsonl` は削除せず保持する。DBが壊れても、抽出結果さえ別途保全されていれば再構築できる（F-04）。

---

## 2. 全体構成

```
                              ┌───────────────────────────┐
  Bluesky / YouTube API       │  data/{platform}/*.jsonl  │
        │                     │        （生データ）        │
        └──── collect ───────▶│                           │
             （cron・自動）    └─────────────┬─────────────┘
                                            │
                                     load（自動・冪等）
                                            ▼
                              ┌───────────────────────────┐
                              │   analysis.duckdb         │
                              │   ├ posts                 │
                              │   ├ insights (+ vector)   │
                              │   ├ edges                 │
                              │   └ extraction_batches    │
                              └──┬────────┬────────┬──────┘
                                 │        │        │
              extract prepare ───┘        │        └─── report（自動・cron可）
                （自動）                   │                    │
                    ▼                     │                    ▼
        data/extract/batch-*.jsonl        │        reports/YYYY-MM-DD.md
                    │                     │                （定量サマリ）
                    ▼                  embed                   │
        ┌───────────────────────┐    （自動・ローカル）          ▼
        │  Claude Code セッション │                     Claude Code が
        │      （手動起動）       │                     洞察を加筆（手動）
        └───────────┬───────────┘
                    ▼
        data/extract/batch-*.result.jsonl
                    │
          extract load（自動・スキーマ検証）
                    │
                    └──────────▶ insights
```

**自動化の境界**: 図中「手動起動」と記した2箇所以外はすべてcronで無人実行できる。

---

## 3. データモデル

### 3.1 posts — 正規化された生データ

プラットフォーム差異を吸収した投稿の共通表現。原文は `raw` に保持する。

| カラム | 型 | 説明 |
|---|---|---|
| `id` | VARCHAR PK | `{platform}:{native_id}` 形式の一意キー |
| `platform` | VARCHAR | `bluesky` / `youtube` |
| `native_id` | VARCHAR | プラットフォーム固有ID（Bluesky: URI、YouTube: videoId） |
| `author_id` | VARCHAR | 投稿者の安定ID（Bluesky: DID、YouTube: channelId） |
| `author_handle` | VARCHAR | 表示用ハンドル |
| `text` | VARCHAR | 本文（YouTubeはタイトル＋説明文を結合） |
| `url` | VARCHAR | 元投稿へのURL |
| `lang` | VARCHAR | 言語コード |
| `posted_at` | TIMESTAMP | 投稿日時（UTC） |
| `collected_at` | TIMESTAMP | 収集日時（UTC） |
| `matched_keywords` | VARCHAR[] | ヒットした検索キーワードのリスト |
| `metrics` | JSON | いいね数・返信数・再生数など（プラットフォーム差異あり） |
| `raw` | JSON | APIレスポンス原文 |
| `extraction_status` | VARCHAR | `pending` / `batched` / `done` / `skipped` |

**重複排除**: `id` の主キー制約により、DB内で完結させる。`SeenStore`（`state/*_seen.json`）は廃止する（ADR-0004）。

**`matched_keywords` について**: 同じ投稿が複数キーワードでヒットしうる。中間テーブルを設けず配列カラムとするのは、DuckDBがLIST型を第一級で扱え、`list_contains()` や `unnest()` で十分に検索・集計できるため。

### 3.2 insights — 凍結された抽出結果

設計方針1.1の中核テーブル。1投稿につき最大1行（洞察が無い投稿は `insight_type='none'` を記録し、再抽出を防ぐ）。

| カラム | 型 | 説明 |
|---|---|---|
| `post_id` | VARCHAR PK/FK | `posts.id` |
| `insight_type` | VARCHAR | `need`（未充足ニーズ） / `complaint`（既存への不満） / `advantage`（差別化の示唆） / `workaround`（自作回避） / `none` |
| `domain` | VARCHAR | 対象領域（`config/domains.yaml` の語彙に制約） |
| `summary` | VARCHAR | **1文の自然言語要約。埋め込みの入力はこのフィールド** |
| `pain_level` | TINYINT | 0〜3。0=言及のみ、3=強い痛み・支払い意思あり |
| `monetizable` | BOOLEAN | 課金可能性が読み取れるか |
| `competitors` | VARCHAR[] | 言及された既存製品・サービス名 |
| `confidence` | FLOAT | 抽出の確信度 0.0〜1.0 |
| `extractor_version` | VARCHAR | 抽出プロンプトのバージョン（例 `v1`） |
| `extracted_at` | TIMESTAMP | 抽出日時 |
| `embedding` | FLOAT[N] | `summary` のベクトル。Nはモデル依存 |

**`summary` を埋め込み対象にする理由**: 投稿本文をそのまま埋め込むと、ノイズ（絵文字・URL・定型句・無関係な話題）が意味ベクトルを汚す。抽出時に「この投稿が示すニーズ」へ圧縮した1文を埋め込むことで、検索精度が大きく上がる。

**`confidence` の用途**: 低確信度の抽出を検索から除外する閾値として使うほか、抽出プロンプト改訂の効果測定にも用いる。

### 3.3 edges — 関係グラフ

汎用的な有向エッジテーブル。専用のグラフDBは導入しない（ADR-0001）。

| カラム | 型 | 説明 |
|---|---|---|
| `src_type` | VARCHAR | `author` / `keyword` / `product` / `domain` / `post` |
| `src_id` | VARCHAR | ソースノードID |
| `dst_type` | VARCHAR | 同上 |
| `dst_id` | VARCHAR | 宛先ノードID |
| `edge_type` | VARCHAR | `mentions` / `cooccurs` / `belongs_to` / `similar_to` |
| `weight` | FLOAT | 出現回数・類似度など |
| `observed_at` | TIMESTAMP | 観測日時 |

主キーは `(src_type, src_id, dst_type, dst_id, edge_type)`。再計算時は `INSERT OR REPLACE` で上書きする。

エッジは投稿・洞察から**導出**されるものであり、一次データではない。いつでも再構築できる。

### 3.4 extraction_batches — 抽出バッチの追跡

| カラム | 型 | 説明 |
|---|---|---|
| `batch_id` | VARCHAR PK | `batch-YYYYMMDD-HHMMSS` |
| `created_at` | TIMESTAMP | バッチ書き出し日時 |
| `post_count` | INTEGER | 対象投稿数 |
| `extractor_version` | VARCHAR | 使用したプロンプトバージョン |
| `loaded_at` | TIMESTAMP | 結果取り込み日時（未取り込みならNULL） |
| `loaded_count` | INTEGER | 取り込み成功件数 |

未取り込みバッチの検出、抽出漏れの追跡に使う。

---

## 4. 機能設計

### 4.1 CLIコマンド体系

既存の `sns-collector` CLIを拡張する。

| コマンド | 自動化 | 説明 |
|---|---|---|
| `sns-collector bluesky` / `youtube` | cron | 既存。収集してJSONLへ追記 |
| `sns-collector db init` | — | スキーマ作成・マイグレーション |
| `sns-collector db load [--since DATE]` | cron | JSONL→DB投入（冪等） |
| `sns-collector extract prepare [--limit N]` | cron | 未抽出投稿をバッチファイルへ書き出し |
| `sns-collector extract load <batch-id>` | 手動 | 抽出結果を検証してDBへ投入 |
| `sns-collector extract status` | — | 抽出待ち件数・未取り込みバッチの一覧 |
| `sns-collector embed [--limit N]` | cron | 未埋め込みの `summary` をベクトル化 |
| `sns-collector graph rebuild` | cron | `edges` を再構築 |
| `sns-collector search <query> [options]` | 手動 | 意味検索＋SQL絞り込み |
| `sns-collector report [--since 7d]` | cron | 定量サマリMarkdown生成 |

### 4.2 ロード処理（F-01〜F-04）

1. 対象JSONLを列挙（`--since` 未指定なら全件）
2. 1行ずつパースし、プラットフォーム別アダプタで `posts` の共通形へ正規化
3. `ON CONFLICT` でバルク投入。`extraction_status` は `pending` で初期化

**冪等性の担保**: 主キー衝突時は既存行を残し、`matched_keywords` だけ既存値との和集合へ更新する。同一ファイルを何度ロードしても件数も内容も変わらない。

**ロード済みファイルを記録しない。** 追跡テーブルを持つと、それと `posts` が乖離したときに「ロードしたのに入っていない」の原因を追えなくなる。判断の材料は `posts` だけにする。ロードが冪等で全件走査が安いため、既定は毎回の全件ロードでよい。`--since` は件数が増えたときの時間短縮に使う。

### 4.3 抽出バッチ（F-05〜F-08）

#### prepare

`extraction_status='pending'` の投稿から `--limit` 件を取り出し、2つのファイルを書き出す。

- `data/extract/<batch-id>.jsonl` — 抽出対象。1行1投稿、`{id, platform, text, posted_at, matched_keywords}` のみを含む（不要フィールドを削ってコンテキストを節約）
- `data/extract/<batch-id>.md` — Claude Codeへの作業指示。抽出スキーマ、判定基準、出力先パス、`insight_type` と `pain_level` の定義、判断に迷う場合の指針を含む

対象投稿の `extraction_status` を `batched` に更新し、`extraction_batches` へ記録する。

#### 抽出（Claude Codeセッション）

ユーザーがセッションを開き、`<batch-id>.md` を読ませて実行する。Claude Codeは `.jsonl` を読み、`data/extract/<batch-id>.result.jsonl` へ1行1結果で書き出す。

#### load

1. 結果ファイルを1行ずつパースし、スキーマ検証（必須フィールド、列挙値、数値範囲）
2. `post_id` がバッチに含まれていたかを照合。含まれない・重複する行は拒否
3. 検証を通った行を `insights` へ投入し、`posts.extraction_status` を `done` に更新
4. 検証エラーは `<batch-id>.errors.jsonl` へ書き出し、該当投稿は `batched` のまま残す（再バッチ対象になる）

**検証を必須とする理由**: 抽出はLLMの出力であり、スキーマ違反・ハルシネーションした `post_id`・範囲外の数値が混入しうる。DBへ入る前に機械的に弾くことで、下流の「確定値」としての信頼性を担保する。

#### 再抽出

`extractor_version` を上げた場合、`sns-collector extract prepare --reextract --version v1` で旧バージョンの投稿を再バッチ対象にできる。旧 `insights` 行は上書きする。

### 4.4 埋め込み（F-10, F-11）

`insights.embedding IS NULL` の行を `--limit` 件取得し、ローカルモデルで `summary` をベクトル化して更新する。モデルとベクトル次元はADR-0002で決定する。

外部APIを一切呼ばないため、cronで無人実行できる（N-02）。

### 4.5 検索（F-09〜F-11）

`search` コマンドは3種の絞り込みを合成する。

| 種別 | 実装 |
|---|---|
| 意味検索 | クエリをローカルモデルでベクトル化し、`insights.embedding` とのコサイン類似度で上位N件 |
| 構造化絞り込み | `insight_type` / `domain` / `pain_level` / `monetizable` / 期間 / プラットフォームのWHERE句 |
| 全文検索 | `posts.text` に対するLIKE / DuckDB FTS拡張 |

すべて同一のSQLクエリ内で合成できる。これがDuckDB採用の主要な理由である（ADR-0001）。

クラスタリング（F-11）は、埋め込みに対する類似度計算をSQLで実行し、閾値以上のペアを `edges` の `similar_to` として記録することで表現する。

### 4.6 レポート（F-14〜F-16）

`report` コマンドは**決定論的な集計のみ**を行い、Markdownを出力する。LLMを呼ばないためcronで完全自動実行できる。

出力内容:

- 期間内の新規観測件数（プラットフォーム別・日次推移）
- `insight_type` 別の分布
- `domain` 別の件数と前期間比
- `pain_level` 3 かつ `monetizable=true` の投稿の全件リスト（最重要シグナル）
- 頻出キーワードと共起ペア上位
- 新規に観測された競合製品名
- 各セクションの代表投稿（URL付き）

洞察・仮説の加筆（F-16）は、この定量サマリを入力としてClaude Codeセッションで行う。生成物は `reports/` 配下に保存する。

---

## 5. 非機能設計

### 5.1 データ配置

| パス | 内容 | git |
|---|---|---|
| `sns-collector/data/{platform}/*.jsonl` | 収集した生データ | ignore |
| `sns-collector/data/analysis.duckdb` | 分析DB本体 | ignore |
| `sns-collector/data/extract/` | 抽出バッチ入出力 | ignore |
| `sns-collector/reports/` | 生成レポート | ignore |
| `sns-collector/config/keywords.yaml` | 検索キーワード定義 | 追跡 |
| `sns-collector/config/domains.yaml` | ドメイン語彙定義 | 追跡 |

### 5.2 バックアップ（N-07）

DBは単一ファイルであるため、`data/` ディレクトリのコピーでバックアップが完結する。週次でバックアップを取る手順をREADMEに記載する。

`insights` は再生成にClaude Codeセッションを要するため最も価値が高い。DB全体のバックアップに加え、`sns-collector db export-insights` でJSONLへエクスポートできるようにする。

### 5.3 規模と性能（N-06）

年間10万件規模を想定する。この規模ではDuckDBの単純なテーブルスキャンでも実用的な応答時間に収まるため、**インデックスは実測して必要になってから追加する**。

ベクトル検索については、DuckDB VSS拡張のHNSWインデックスの永続化に実験的フラグを要する可能性があるため、Phase 3で挙動を確認する。10万件規模であればインデックスなしの総当たり計算でも許容範囲に収まる見込みであり、これを既定とする。

### 5.4 スキーマ変更

`schema_version` テーブルでバージョンを管理し、`db init` が差分を適用する。マイグレーションは前方向のみとし、ロールバックはバックアップからの復元で対応する。

### 5.5 エラー処理方針

| 箇所 | 方針 |
|---|---|
| 収集（既存） | HTTPエラー時はそのrunを失敗させる。次回cronで自然にリトライ |
| ロード | 不正行はスキップしてログに記録。処理全体は継続 |
| 抽出結果の取り込み | 検証エラー行は拒否し `errors.jsonl` へ。該当投稿は再バッチ対象として残す |
| 埋め込み | モデルロード失敗は即座に中断（部分的な埋め込みは検索品質を損なうため） |

### 5.6 テスト方針

- 正規化アダプタ、スキーマ検証、集計ロジックは単体テスト対象とする
- 抽出結果ファイルの検証は、正常系・スキーマ違反・不正 `post_id`・重複のフィクスチャで網羅する
- 実際のAPI通信・LLM呼び出しはテストで行わない（既存方針を踏襲）
- ロード処理の冪等性は「同一ファイルを2回ロードして件数が変わらない」ことをテストで担保する

---

## 6. 設計上のリスク

| リスク | 影響 | 対応 |
|---|---|---|
| 抽出品質が期待に届かない | 洞察が得られない | Phase 2で少数バッチを試行し、プロンプトを反復改善してからスケールする |
| キーワード設計が空振りする | データが集まらない | Phase 0で収集を先行させ、実サンプルを見てから設計を確定する |
| 手動抽出の運用が続かない | パイプラインが停止する | 1バッチの所要時間を実測し、週1回15分以内に収まる件数に調整する |
| 日本語埋め込みモデルの性能不足 | 意味検索が機能しない | Phase 3で複数モデルを実データで比較する（O-02） |
| ベクトル検索が規模に耐えない | 検索が遅い | 10万件規模までは総当たりで許容。超えた時点でインデックス導入を検討 |
