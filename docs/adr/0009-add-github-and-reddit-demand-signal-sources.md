# ADR-0009: GitHub IssuesとRedditを需要シグナルの収集元として追加する

- ステータス: 採用
- 日付: 2026-08-10
- 関連: [ADR-0005](./0005-reassess-demand-signal-sources.md) / [ADR-0006](./0006-add-hackernews-demand-signal-source.md) / [requirements.md](../requirements.md) §3.1 / [design.md](../design.md) §4.3

## コンテキスト

ADR-0006はHacker Newsを4つ目でなく3つ目の収集元として追加したが、「ADR-0005が挙げた他の候補（Reddit・Mastodon系・はてなブックマーク）は却下していない。他候補の検討は依然開いている」と明記して終わっている。加えて同ADRの実収集データでは、Hacker Newsもfabricationの痛み率が44%→14%へ下がり、`ai_accuracy`ドメインの弱さがBlueskyと同じ形で再現するなど、「困りごとの一人称表現」を持つコーパスの不足が収集元を1つ増やしただけでは解消しないことが分かった。

この状況で、マーケティングデータパイプラインの別トピック（maritime-collector、船舶衝突予知・予防）の深掘り調査の一環として、無料で取得できる新しい情報源を検討した。GitHub Issues（バグ報告・機能要望が一人称の困りごととして構造的に集積する）とRedditの全文検索（相談・不満スレッドが集まる）が候補として浮かび、両方を追加する判断をした。

選定基準はADR-0006を引き継ぐ。

- **認証要否**: ADR-0005が「Redditは認証が要り、鍵の管理範囲が広がる」ことを不利益として明記した基準をそのまま使う
- **既存アーキテクチャとの適合**: `sns_collector`の収集モジュールは「キーワード検索API → JSONL → DB」という型を前提にする（`bluesky/` `youtube/` `hackernews/`）
- **対象ドメイン読者層との重なり**: バグ報告・相談スレッドの一次情報が取れるか

### 検討した選択肢

| 案 | 却下理由 |
|---|---|
| GitHub Issues（REST検索API `/search/issues`） | 採用。認証は任意（未設定でも動く。設定するとレート制限が10→30 req/minへ緩和）。既存の「キーワード検索→JSONL→DB」の型をそのまま使える。バグ報告・機能要望が一人称の困りごととして構造的に集積する唯一の候補 |
| GitHub Discussions（GraphQL API） | 却下。GraphQLはPOST+クエリ本文であり、`common/http.py::get_json`が前提とするGET抽象に乗らない。より本質的には、GraphQLはエラーをHTTP 200 + `errors`配列で返すため、既存の再試行判定（`response.status_code`依存）では失敗が沈黙して空配列を返す新しい失敗モードを持ち込む。Issuesの実測後に別途検討する |
| Reddit（全文検索API `oauth.reddit.com/search`） | 採用。ADR-0006が却下理由として挙げた「サブレディット単位の購読はキーワード検索と収集モデルが異なる」は、購読モデルを使わず全サブレディット横断のキーワード検索を使うことで解消する。OAuth認証の鍵管理コストは解消せず、受け入れる不利益として扱う |
| Reddit（サブレディット単位の購読） | 却下。ADR-0005・ADR-0006が指摘したとおり`posts.matched_keywords`の再定義が要る。全文検索で同じ母集団に届くため採る理由が無い |
| Mastodon系・はてなブックマーク | 本ADRでは扱わない。ADR-0006の却下理由（インスタンス分散・日本語圏限定）が変わっていない |

## 決定

**GitHub Issues（REST検索API）とReddit（application-only OAuth2による全文検索API）を、4つ目・5つ目の収集プラットフォームとして追加する。役割はいずれもBluesky・Hacker Newsと同じ需要シグナルとする。ただし抽出（`extract prepare`）の既定対象には含めず、`--platform`の明示指定でのみ対象とする。**

判断の根拠:

1. **ADR-0006がRedditについて挙げた却下理由のうち、収集モデルの不整合は解消した。** サブレディット購読ではなく`GET /search`（全サブレディット横断のキーワード検索）を使うため、既存の「キーワード→検索→JSONL→DB」の型がそのまま成立し、`posts.matched_keywords`の意味論はBluesky・Hacker Newsと変わらない。サブレディット限定はキーワード文字列内の`subreddit:X`構文で表現でき、コードに概念を持ち込まない
2. **OAuth認証の鍵管理コストは解消せず、受け入れる不利益として扱う。** `.env`に`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT`の3項目が増える。引き換えに、Hacker Newsで不足した「困りごとの一人称表現の集積」への到達を狙う
3. **GitHubは認証を任意にし、鍵が増える範囲をReddit側に限定した。** 未認証でも動くため、キーワード候補を実データで検証する既存の運用（`sns-collector/CLAUDE.md`「質の確認に本収集を使わない」）をGitHubでも継続できる
4. **新しい抽象化は、この機能が実際に持ち込んだ構造差にのみ対応させ、既存3プラットフォームのコードには触れない。** 認証方式が初めて4種類（無し/クエリキー/任意Bearer/必須OAuth2）に分岐する点に対応して`common/http.py`へ`headers`引数と`post_json`を追加し、Redditのトークン取得・キャッシュ・期限判定を検索呼び出しから分離する`reddit/auth.py::TokenProvider`を新設した。それ以外の`client.py` / `models.py` / `search.py`は既存3プラットフォームと同一構造の複製である
5. **既定の抽出対象には含めない。** ADR-0006はHacker Newsを既定へ入れる判断を実収集の痛み率実測とセットで行っており、GitHub/Redditにはまだ実測が無い。GitHub Issue本文はBluesky投稿より1〜2桁長く、未検証のまま既定バッチ（`extract prepare --limit 20`の既定）に混ぜると、課金される構造化抽出セッションのコンテキストを圧迫しうる

## 結果

### 実装した内容

- `src/sns_collector/github/`（`client.py` / `models.py` / `search.py`）・`src/sns_collector/reddit/`（`client.py` / `models.py` / `search.py` / `auth.py`）を、既存の`bluesky/` `hackernews/`と同じ構成で追加した
- `common/http.py`に`headers`引数と`post_json`関数を追加した。既存3プラットフォームの呼び出しは無変更で通る(完全後方互換)
- `db/adapters.py`に`from_github` / `from_reddit`を追加した。**スキーマ変更（マイグレーション）は不要だった**（`platform`列はVARCHARでCHECK制約を持たない。ADR-0006と同じ結論）
- `extract/prepare.py`の`DEFAULT_PLATFORMS`は`("bluesky", "hackernews")`のまま変更していない
- `typing.Protocol`は導入しなかった。`sns-collector/pyproject.toml`にmypy/pyright等の型チェッカーが無く、CIも`ruff`+`pytest`のみのため、Protocolを書いても実行時に検証されずドキュメント価値のみになる。代わりに`set(cli.COLLECTORS) == set(ADAPTERS)`を検証する実行可能なテストを追加し、レジストリの整合をCIで機械的に担保した

### 既定抽出対象への昇格基準

初回収集後、`keywords quality`の痛み率代理指標をHacker Newsの実績（fabrication 14%、edge_ai 1%、ai_accuracy 0%）と比較する。同水準以上であれば`DEFAULT_PLATFORMS`への追加を検討する。GitHubは追加でIssue本文の長さ分布も確認し、`extract prepare --limit`の既定値を圧迫しないか見る。

### 受け入れる不利益

- Reddit用のOAuth資格情報3項目が`.env`に増える（ADR-0005が明記した不利益をそのまま抱える）
- GitHub検索APIのレート制限が未認証10 req/min・認証済み30 req/minと他プラットフォームより1桁低く、`github/client.py`は6.5秒（未認証）/2.5秒（認証済み）のペーシングが要る。キーワードを増やすとrun時間が線形に伸びる
- `common/http.py`にPOST経路（`post_json`）が増えた。全プラットフォームが通る共有部品の分岐が1つ増える
- GitHub Discussionsは取れない（GraphQL特有の失敗モードのため意図的にスコープ外）

### 未解決のまま残る事項

- **Reddit「script」アプリ登録（https://www.reddit.com/prefs/apps）は人手の外部作業であり、コードでは解消できない。** これが済むまでReddit収集は実行できない（実装・テストは完了している）
- `maritime-collector/config/keywords.yaml`・`sns-collector/config/keywords.yaml`への`github:` / `reddit:`セクション追加は本ADRのスコープ外。他の全プラットフォーム追加時と同じく、実データでの検証を先に行う
- `sns-collector/scripts/cron_run.sh`・`maritime-collector/scripts/cron_run.sh`のusage文字列・`case`分岐への追記、crontabへの実登録は行っていない。キーワード検証後の運用作業として残る
- GitHub Discussions（GraphQL）は取れない。Issuesの実測結果が有望であれば、GraphQL用のエラー処理層を別途設計してから検討する
- Mastodon系・はてなブックマークはADR-0006と同じ理由でスコープ外のまま。他候補の検討は依然開いている
