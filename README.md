# marketing-data-pipeline

SNS上の投稿から市場の潜在的な顧客要望・製品優位性を継続的に収集・構造化し、個人開発の事業仮説を立てるためのローカル分析基盤。詳細は `CLAUDE.md` と `docs/design.md` を参照する。

## システム構成

[docs/architecture.md](docs/architecture.md) にC4モデルで書いた構成図が4枚ある。外部サービスとの連携と送信内容はSystem context図、通信プロトコルはContainer図、処理順と自動化の境界はDynamic図、ハードウェア境界はDeployment図で確認する。

## モニタリング画面

```sh
task dashboard:setup   # 初回のみ。dashboard配下のPython依存関係を入れる
task dashboard         # http://127.0.0.1:8787 で起動する
```

常駐サーバとして起動し、ブラウザをリロードするたびにファイルを読み直す。更新のためにサーバを再起動したり、何かを再生成したりする操作は不要。

**この画面がまだ表示できないもの**: 収集した投稿本文・構造化抽出結果（`insights`）・抽出待ち件数といった `sns-collector/data/analysis.duckdb` の中身は、この画面のどのページからも見えない。画面が対象にしているのは開発ルール・ADR・生成レポート・収集ログ・ガードレールメトリクスであり、生成レポート（`sns-collector/reports/`）は対応する自動生成コマンドが未実装のため現状は空になる（`docs/roadmap.md` Phase 5）。

抽出の進捗やドメイン別件数、キーワードの質を見るには `sns-collector` ディレクトリで以下を使う。

```sh
uv run sns-collector extract status                        # 抽出待ち件数・ドメイン別件数
uv run sns-collector keywords quality --platform bluesky   # キーワード別の質（困りごと表現の代理指標）
```
