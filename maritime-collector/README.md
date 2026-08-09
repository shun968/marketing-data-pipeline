# maritime-collector

船舶/AR/衝突予知・衝突予防をテーマにしたSNS分析の独立インスタンス。

`sns-collector/` と同じ収集→抽出→埋め込み→グラフ→レポートのパイプラインを、設定・データベース・収集クオータを完全に分離した状態で再利用する（背景は `docs/adr/0008-reuse-sns-collector-across-topics.md`）。このディレクトリ自体はPythonコードを持たず、`sns-collector/` のCLIを別の設定ファイル・別のDBへ向けて呼び出すだけの薄い構成になっている。

**現状（2026-08-10時点）: キーワード・ドメインは未検証のドラフトである。** cronへは未登録。以下の検証手順を済ませてから定期収集を有効にすること。

## セットアップ

`sns-collector/` 側のセットアップ（`uv sync`、Bluesky/Hacker Newsの認証設定）が済んでいることが前提。追加の認証設定はBluesky/Hacker Newsの範囲では不要（両者ともAPIキー不要）。

```sh
cd maritime-collector
uv run --project ../sns-collector sns-collector db init --data-dir data --db data/analysis.duckdb
```

## キーワード候補の検証（cron登録の前に必ず行う）

`config/keywords.yaml` の候補はまだ実データで確認していない。`sns-collector/CLAUDE.md`「質の確認に本収集を使わない」と同じ手順で、DBを汚さずに検証する。

```sh
cd sns-collector
uv run python -c "
from sns_collector.bluesky.client import search_posts
hits = search_posts('ARPA 使いにくい', sort='latest', limit=50)
for h in hits[:10]:
    print(h.get('author', {}).get('handle'), '|', h.get('record', {}).get('text', '')[:80])
"
```

ヒット件数・投稿者アカウントの多様性・本文の質を見て、`sns-collector/README.md`「検索キーワードの編集」の3原則（アンカー語・英字への日本語併記・英語は件数でなくアカウント多様性で判定）に照らして判断する。確認できたキーワードには `config/keywords.yaml` に `[実測◎/○/△]` を付け、改訂履歴に根拠を残す。

## 手動実行

```sh
cd maritime-collector
uv run --project ../sns-collector sns-collector bluesky \
  --keywords config/keywords.yaml --data-dir data --db data/analysis.duckdb
uv run --project ../sns-collector sns-collector hackernews \
  --keywords config/keywords.yaml --data-dir data --db data/analysis.duckdb

uv run --project ../sns-collector sns-collector keywords quality \
  --platform bluesky --data-dir data --db data/analysis.duckdb
```

**cwdを `sns-collector/` へ移して実行しないこと。** 理由は `CLAUDE.md` を参照。

## 構造化抽出・埋め込み・グラフ・レポート

コマンド体系は `sns-collector/README.md` と同じ。`--data-dir`/`--db`/`--domains`/`--reports-dir` にこのディレクトリのパスを渡す点だけが違う。

```sh
uv run --project ../sns-collector sns-collector extract prepare \
  --data-dir data --db data/analysis.duckdb --domains config/domains.yaml \
  --prompts-dir prompts --version v1

uv run --project ../sns-collector sns-collector extract load <batch-id> \
  --data-dir data --db data/analysis.duckdb --domains config/domains.yaml

uv run --project ../sns-collector sns-collector embed --data-dir data --db data/analysis.duckdb

uv run --project ../sns-collector sns-collector graph rebuild --data-dir data --db data/analysis.duckdb

uv run --project ../sns-collector sns-collector report --data-dir data --db data/analysis.duckdb --reports-dir reports
```

`--prompts-dir prompts --version v1` を必ず指定すること。省略すると `sns-collector/prompts/` の（このトピックとは無関係な）プロンプトが使われてしまう。

## 定期実行(cron)

キーワードの検証が済んでから登録する。`scripts/cron_run.sh` は `bluesky` / `hackernews` / `report` の3コマンドに対応する（`extract`/`embed`/`graph rebuild` は手動運用。理由は`sns-collector/README.md`と同じ）。

```cron
5  */3 * * * /path/to/marketing-data-pipeline/maritime-collector/scripts/cron_run.sh bluesky
35 */3 * * * /path/to/marketing-data-pipeline/maritime-collector/scripts/cron_run.sh hackernews
10 9   * * 1 /path/to/marketing-data-pipeline/maritime-collector/scripts/cron_run.sh report
```

分をsns-collector本体（`0/15/30`, `9:00`月曜）とずらしているのは、同一IPからの連続アクセスによるレート制限回避のため。

## 対象外にしていること

- **YouTube。** 使うかどうか未定。使う場合、sns-collector本体のクオータと分けるため別のGoogle Cloud Projectと `YOUTUBE_API_KEY` が要る
- **ダッシュボード。** `dashboard/` は現状sns-collector本体のレポート・ログのみを固定パスで読む。maritime-collectorのレポートは表示されない
