# CLAUDE.md — maritime-collector

船舶/AR/衝突予知・衝突予防をテーマにしたSNS収集の独立インスタンス(ADR-0008)。

**このディレクトリはPythonコードを持たない。** `../sns-collector/` のCLI（`sns_collector`パッケージ）を、設定ファイルの向き先だけ変えて再利用する。収集・抽出・埋め込み・グラフ・レポートの実装、失敗モード対策、キーワード設計の原則、秘匿情報の扱いは全て `../sns-collector/CLAUDE.md` と `../sns-collector/README.md` に従う。ここには書き写さない。

## このディレクトリ固有の情報

- `config/domains.yaml` / `config/keywords.yaml` — このトピック専用。sns-collector本体のものとは独立している。**未検証のドラフト。** 実データでの確認手順は `README.md` を参照
- `prompts/extract-v1.md` — このトピック専用の抽出プロンプト。トピック非依存部分は `sns-collector/prompts/extract-v2.md` から引き継いでいる（ADR-0008）
- `scripts/cron_run.sh` — このトピック専用のcronラッパー。`sns-collector/scripts/cron_run.sh` と同型だが、全コマンド呼び出しに `--data-dir`/`--keywords`/`--db`/`--reports-dir` を明示し、sns-collector本体のdata/state/reportsには一切触れない
- `data/` `state/` `reports/` — 収集データ・状態・生成レポート。`.gitignore`済み。**絶対にコミットしない**（`scripts/check-no-private-data.sh` がsns-collector分と同様にこちらも検査する）

## コマンド実行の形

`uv`のプロジェクト解決は `sns-collector/` にある `pyproject.toml` を必要とするため、このディレクトリ単体では `uv run sns-collector` は動かない。`--project` でsns-collector側の環境を指定しつつ、cwdはこのディレクトリに留める。

```sh
uv run --project ../sns-collector sns-collector db init --data-dir data --db data/analysis.duckdb
uv run --project ../sns-collector sns-collector bluesky --keywords config/keywords.yaml --data-dir data --db data/analysis.duckdb
```

cwdを `sns-collector/` へ移して実行しないこと。`--data-dir` などを相対パスで渡したときに、解決先が本体側へずれる。

鍵を要する収集元を足す場合、環境ファイルはこのディレクトリ配下に置かず `SNS_COLLECTOR_ENV_FILE` で外部を指す（ADR-0012）。
