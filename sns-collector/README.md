# sns-collector

潜在的な新規事業開拓のための分析材料として、Bluesky・YouTubeのキーワード検索データを定期収集するツール。

収集データ・状態ファイルは常にローカルディスクにのみ保存され、GitHub等の外部には一切送信・コミットされない（`.gitignore`済み）。

## 前提

- Python 3.11以上
- [uv](https://docs.astral.sh/uv/)

## セットアップ

```sh
cd sns-collector
uv sync
```

### Bluesky

認証不要。追加設定なしですぐ実行できる。

### YouTube

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成（または既存プロジェクトを使用）
2. 「APIとサービス」→「ライブラリ」から **YouTube Data API v3** を有効化
3. 「認証情報」→「認証情報を作成」→「APIキー」でキーを発行
4. `.env`を作成し、キーを設定する

```sh
cp .env.example .env
```

```
YOUTUBE_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 検索キーワードの編集

`config/keywords.yaml`を編集する。BlueskyとYouTubeは独立したキーワードリストを持つ。

```yaml
bluesky:
  sort: latest # latest | top
  limit_per_keyword: 50
  keywords:
    - "新規事業"

youtube:
  order: relevance # relevance | date | rating | viewCount
  max_results_per_keyword: 25
  region_code: JP
  relevance_language: ja
  keywords:
    - "新規事業 アイデア"
```

## 手動実行

```sh
uv run sns-collector bluesky
uv run sns-collector youtube
```

## 出力

`data/{bluesky,youtube}/<YYYY-MM-DD>.jsonl`に1行1JSONで追記される（同日内の複数回実行は同一ファイルに追記）。

run跨ぎの重複を避けるため、既知の投稿ID/動画IDは`state/{bluesky,youtube}_seen.json`に永続化される（60日経過したエントリは自動的に破棄）。同じキーワードで再実行しても、既に収集済みの投稿・動画は再度JSONLに書き込まれない。

## 定期実行(cron)

`scripts/cron_run.sh`はcron向けのラッパースクリプトで、以下を行う。

- `flock`による多重起動防止（前回実行がまだ終わっていなければ即座にスキップしログに記録）
- `bash -lc`経由での実行（cronは最小限のPATHしか持たないため、ログインシェル相当の環境を読み込んでから`uv`を呼び出す。特にこの環境ではsnapサンドボックスの影響で`uv`が`$HOME/snap/code/.../bin`のような特殊なパスに配置されており、非ログインシェルではPATHが通らないため必須）

`crontab -e`で以下のように登録する（パスは絶対パスで指定すること）。

```cron
# Blueskyキーワード検索(3時間おき)
0 */3 * * * /path/to/marketing-data-pipeline/sns-collector/scripts/cron_run.sh bluesky
# YouTubeキーワード検索(3時間おき、Blueskyと15分ずらして負荷分散)
15 */3 * * * /path/to/marketing-data-pipeline/sns-collector/scripts/cron_run.sh youtube
```

実行ログは`state/.logs/{bluesky,youtube}.log`に記録される。

### YouTubeのクオータと実行頻度

`search.list`は1回100クオータユニットを消費し、1日の無料枠は10,000ユニット。

```
1日あたりの実行可能回数 ≈ 10000 / (100 × keywords件数)
```

例えばキーワードが3件なら、1日あたり最大約33回まで実行可能。`config/keywords.yaml`のキーワード数とcronの実行頻度のバランスはこの式を目安に調整すること。

## テスト

```sh
uv run pytest
```

実際のAPI通信は行わず、`requests`をモックした単体テストのみ。

## 制約・注意事項（MVPスコープ外）

- YouTubeのコメント取得（動画メタデータのみ）
- GitHub Actions等クラウド上での自動実行（リポジトリがPublicであり、収集データを非公開に保つためローカルcronのみをサポート）
- データウェアハウス等への自動ロード
- 検索結果のページング（1キーワード1ページのみ取得。定期実行によって自然にカバレッジが積み上がる設計）
- リトライ・バックオフの高度な制御（HTTPエラー時はそのrunが失敗するのみ）
- ログローテーション（`state/.logs/`配下は定期的に手動で確認・削除すること）
