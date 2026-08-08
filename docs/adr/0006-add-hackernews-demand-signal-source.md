# ADR-0006: Hacker Newsを需要シグナルの追加収集元として採用する

- ステータス: 採用
- 日付: 2026-08-08
- 関連: [ADR-0005](./0005-reassess-demand-signal-sources.md) / [requirements.md](../requirements.md) §3.1 / [design.md](../design.md) §4.3

## コンテキスト

ADR-0005で「Bluesky単独では需要シグナルの流入が足りない」と判断し、収集元の追加を次の検証項目とした。同ADRは候補（Reddit の r/3Dprinting・r/LocalLLaMA、Mastodon系、はてなブックマーク）を挙げたが、「どれを採るかはこのADRでは決めない」として選定を保留した。

本ADRはその選定を行う。対象はADR-0005が挙げた候補と一致しない（Hacker Newsは挙がっていなかった）。選定基準を以下に置く。

- **認証要否**: ADR-0005は「Redditは認証が要り、`.env`に資格情報が増え、鍵の管理範囲が広がる」ことを受け入れる不利益として明記した。認証不要な収集元はこのコストを増やさない
- **既存アーキテクチャとの適合**: `sns_collector`の収集モジュールは「キーワード検索API → JSONL → DB」という型を前提にしている（`bluesky/` `youtube/`）。全文検索APIを持つ収集元はこの型をそのまま再利用できる
- **対象ドメインの読者層との重なり**: `config/domains.yaml`の`edge_ai`（エッジデバイスでのAI実行）・`fabrication`（3Dプリンタ・自作装置）は、ホビイスト・個人開発者層の発話を前提にしている

### 検討した選択肢

| 案 | 却下理由 |
|---|---|
| Reddit（r/3Dprinting、r/LocalLLaMA） | OAuth認証が必須。ADR-0005が「鍵の管理範囲が広がる」と明記した不利益をそのまま抱える。サブレディット単位の購読はキーワード検索と収集モデルが異なり、`posts.matched_keywords`の再定義が要る（ADR-0005で指摘済み、未解決） |
| Mastodon系 | インスタンスが分散しており、単一の全文検索APIが無い。どのインスタンスを対象にするかの選定自体が別の調査になる |
| はてなブックマーク | 対象が日本語圏に閉じる。ADR-0005の課題は英語圏キーワード追加後も解消しなかった「Bluesky単独の流入不足」であり、日本語圏への収集元追加は同じ在庫の枯渇を繰り返す可能性が高い |
| Hacker News（Algolia検索API） | 採用。認証不要、既存の「キーワード検索→JSONL」の型をそのまま使える。ただしコーパスの厚みはBlueskyより小さい（後述） |

## 決定

**Hacker News（Algolia検索API `hn.algolia.com`）を、Bluesky・YouTubeに続く3つ目の収集プラットフォームとして追加する。役割はBlueskyと同じ需要シグナルとし、抽出（`extract prepare`）の既定対象にも含める。**

判断の根拠:

1. **認証不要でADR-0005の不利益を増やさない。** `.env`への追加は不要。既存の`common/http.py`のペーシング・再試行機構をそのまま使える
2. **コメント本文・Ask HN投稿という生の一人称表現が取れる。** ストーリー本文（タイトル・URLのみ）に留まらず、返信コメントを検索対象に含めることで、Blueskyの投稿本文に相当する生の困りごと表現を拾える
3. **既存の3ファイル構成（client/models/search）をそのまま複製できる。** 新しい抽象化を要求しない

## 結果

### 実装した内容

- `src/sns_collector/hackernews/`（`client.py` / `models.py` / `search.py`）を、既存の`bluesky/` `youtube/`と同じ構成で追加した
- `db/adapters.py`に`from_hackernews`を追加し、`platform`列に`hackernews`を持つ行として`posts`へ正規化する。**スキーマ変更（マイグレーション）は不要だった**（`platform`列はVARCHARでCHECK制約を持たない）
- `extract/prepare.py`の`DEFAULT_PLATFORMS`に`hackernews`を追加した。YouTubeと異なり構造的に`none`にしかならない制約が無いため

### コーパスの厚みがBlueskyと桁違いに違う

事前確認（Algolia検索APIへの直接問い合わせ、収集は行っていない）で、Blueskyで機能した4語以上の完全一致フレーズがHacker Newsではほぼ0件になることを確認した。

```
"jetson nano slow"      0件
"3d print failed"       0件（Blueskyでは◎だった語がHNでは0件）
"resin print failed"    0件
"yolo false positives"  0件
```

2〜3語のフレーズに絞って初めて件数が出た。**キーワードはプラットフォームごとに別建てで検証する**という既存の原則（`config/keywords.yaml`）が、3つ目のプラットフォームでも成立した。

### 実収集データでの検証（2026-08-08追記）

初回収集（203件、8キーワード）をDBで評価した。判定はBluesky側と同じ正規表現による代理指標（キーワード単位の数値は`config/keywords.yaml`改訂履歴を見ること）。

```
fabrication  88件  痛み14%  ← Blueskyの44%を大きく下回る
edge_ai      99件  痛み 1%
ai_accuracy  16件  痛み 0%
```

**`ai_accuracy`ドメインの弱さは実データでも裏付けられた。** 事前確認時点の懸念どおり、Blueskyと同じ構造的な弱さが再現している。

**新しいノイズ源を確認した。** `"model accuracy" edge`の16件中11件（69%）が、月次の求人スレッド「Ask HN: Who is hiring?」への定型応募コメントだった。Blueskyのブリッジ投稿・論文botとは異なる、Hacker News固有のノイズ形態である。

**fabricationの痛み率がBlueskyより大幅に低い（44%→14%）。** キーワードの質が落ちたのではなく、コーパス自体が薄く「作例紹介」「技術論評」が「一人称の困りごと」より多いことが主因と見られる。この点は`config/domains.yaml`側の判断材料としてはまだ反映していない（3ドメイン中では最良のままだが、Bluesky水準の期待はできない）。

### 受け入れる不利益

- **`ai_accuracy`ドメインの弱さがHacker Newsでも再現している。** Blueskyと同じ構造的な弱さであれば、収集元を増やしても解決しない
- **キーワード8語は初期値であり、他プラットフォームより少ない。** 収集データが溜まってから増減を判断する
- **cronへの登録はまだ完了していない。** `scripts/cron_run.sh hackernews`の追加登録は運用作業として残っている（システムのcrontab変更は本セッションの自動実行権限では行えなかった）

### 未解決のまま残る事項

- ADR-0005が挙げた他の候補（Reddit・Mastodon系・はてなブックマーク）は却下していない。本ADRはHacker Newsを追加しただけであり、他候補の検討は依然開いている
- Hacker Newsのキーワード改訂（8語からの増減。特に`"model accuracy" edge`の求人枠混入69%をどう扱うか）
- `reopen_for_reextraction`・`extract prepare`のプラットフォーム別動作は3プラットフォーム構成で回帰テストを足したが、実運用（cron 3本立て）での排他ロック衝突は実測していない
- fabricationの痛み率低下（44%→14%）が一時的なサンプルの偏りか、Hacker News固有の傾向かは、継続収集で確かめる必要がある
