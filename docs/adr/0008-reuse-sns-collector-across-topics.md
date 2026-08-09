# ADR-0008: トピックごとにコードを複製せず、同じsns_collectorパッケージを異なる設定へ向けて再利用する

- ステータス: 採用
- 日付: 2026-08-10
- 関連: docs/adr/0001-duckdb-for-analysis-store.md / maritime-collector/CLAUDE.md / maritime-collector/README.md

## コンテキスト

`sns-collector/` はAI精度・エッジAI・3Dプリンタという1つの事業テーマに紐づいて設計されている。全く異なるテーマ（船舶/AR/衝突予知・衝突予防）を並行して調査したいが、既存テーマのconfig・DB・収集APIクオータとは完全に分離したい。データが混ざると、レポート・グラフ・検索結果の集計に両テーマが混在してしまう。

調査の結果、`sns_collector`のCLI（`sns-collector/src/sns_collector/cli.py`）はほぼ全コマンドで `--data-dir` / `--keywords` / `--domains` / `--db` / `--reports-dir` を明示的に上書きできる設計になっていた。唯一、抽出プロンプトの探索先（`extract/prepare.py`の`PROMPTS_DIR`）だけがハードコードされており、トピック非依存な再利用の抜け穴だった。

### 検討した選択肢

| 案 | 却下理由 |
|---|---|
| 新規Gitリポジトリを作る | CI・lefthook・ADR運用・秘匿情報ガード等をゼロから用意するコストが大きい。本リポジトリ内の新ディレクトリで足りると判断した |
| sns-collector一式（bluesky/youtube/hackernewsクライアント・db・extract・embed・graph・report）を丸ごと複製する | 同じ失敗モード対策・同じバグ修正を2箇所で保守することになる。CLAUDE.mdが繰り返し指摘する「1箇所で直して別の箇所を直し忘れる」失敗パターンをそのまま再現する |
| 既存の`sns-collector/config/keywords.yaml`・`domains.yaml`に新テーマのドメイン・キーワードを追加する | 収集APIクオータ（特にYouTube）を既存テーマと分け合うことになり、レポート・グラフ・検索結果も両テーマが混ざる |

## 決定

**同じ`sns_collector`パッケージ・同じCLIを、設定ファイル（config）とデータベース（DB）の向き先だけ変えて再利用する。トピックごとの独立ディレクトリ（例: `maritime-collector/`）はPythonコードを一切持たず、`config/`・`prompts/`・1本のcronラッパースクリプトのみを置く。**

判断の根拠:

1. **CLIが既にほぼ全コマンドでパスの上書きに対応していた。** `--data-dir`/`--keywords`/`--domains`/`--db`/`--reports-dir`により、新規のPythonコードを書かずに完全に独立したデータツリーへ書き込める。
2. **コード複製よりも保守コストが低い。** 収集の失敗モード対策（JSONL先書き・エラー隔離）、DuckDBスキーマ、抽出結果の検証ロジック等はトピックに依存しない実装であり、1箇所で直せば全トピックに効く。
3. **抽出プロンプトだけコード変更が必要だった。** `PROMPTS_DIR`が唯一の上書き不可能な依存だったため、`prompt_path()`/`_read_template()`/`prepare()`へ`prompts_dir`引数を追加した（既定`None`で既存動作を保つ後方互換の変更）。CLIには`--prompts-dir`を追加した。
4. **`uv run --directory <topic> --project <sns-collector>`でcwdを明示的にトピック側へ留めたまま、依存解決だけをsns-collector側へ委ねる。** cronラッパー（`maritime-collector/scripts/cron_run.sh`）は`cd`でsns-collector/へ移動しない。cwdを移動すると、python-dotenvが実行時cwdから`.env`を探すため、将来`maritime-collector/.env`を置いてもsns-collector本体の`.env`が誤って使われてしまう。

## 結果

新しいトピックの追加は、`config/keywords.yaml`・`config/domains.yaml`・`prompts/extract-v1.md`・`scripts/cron_run.sh`・簡単な`README.md`/`CLAUDE.md`を書くだけで済み、新規の`pyproject.toml`・新規CIジョブは不要になった。`.github/workflows/ci.yml`の`guards`ジョブはリポジトリ全体の`*.sh`/`*.yml`/`*.yaml`を対象にしており、新ディレクトリのシェルスクリプト・YAMLは自動的にカバーされる。

受け入れた不利益と残る作業:

- **安全側ガードは、トピックディレクトリが`*-collector/`という命名規約に沿う前提でのみ、追加の手動編集なしに機能する。** `check-no-private-data.sh`と`.gitignore`は`*-collector/data|state|reports`というワイルドカードで判定しており、`check-doc-duplication.sh`の`is_prompt()`も特定のディレクトリ名に依存しない正規表現にしてある。**規約から外れた名前（例: `maritime` のように接尾辞を付けない）を選んだ場合は自動検知できない。** ディレクトリの存在だけでは「収集データ用ディレクトリだ」と機械的に判定できないため、命名規約という運用上の合意に依存している点は変わらない。
- **`dashboard/`は複数トピックに対応していない。** `dashboard/src/dashboard/paths.py`がsns-collector本体の`reports`/`state/.logs`を固定パスで読むため、新トピックのレポートはダッシュボードに表示されない。複数インスタンス対応は別途の機能追加として扱う。
- **YouTube収集を使う場合、別のGoogle Cloud Project・APIキーが要る。** クオータ分離はコード上の仕組みではなく、キー発行という運用上の対応に委ねている。
- **キーワード・ドメイン定義は本ADRの対象外。** `maritime-collector/config/`の中身は実データ検証前のドラフトであり、既存3ドメインと同じくPhase 0相当の反復改訂を経る前提である。
