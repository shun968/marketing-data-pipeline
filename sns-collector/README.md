# sns-collector

潜在的な新規事業開拓のための分析材料として、Bluesky・YouTube・Hacker News・GitHub・Redditのキーワード検索データと、Hacker Newsの求人・案件スレッド（hnjobs）を定期収集するツール。

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

### Hacker News

認証不要。Algoliaが提供する公開検索API（`hn.algolia.com`）を使うため、追加設定なしですぐ実行できる。

### 鍵の置き場所（認証が要る収集元の共通の前提）

**環境ファイルはこのリポジトリの中に置かない**（ADR-0012）。既定の場所は次のとおりで、`scripts/cron_run.sh` がこのパスを `SNS_COLLECTOR_ENV_FILE` へ入れて実行する。

**次はホスト側で実行する。**（devcontainer内のホームは `.claude` / `.config/gh` を除いて再作成のたびに消え、ホスト側のcronからも見えない。収集を回すのはホストである。）

```sh
mkdir -p ~/.config/sns-collector
cp .env.example ~/.config/sns-collector/.env
chmod 600 ~/.config/sns-collector/.env
```

別の場所に置く場合は `SNS_COLLECTOR_ENV_FILE` にそのパスを設定する。手で実行するときも同じで、変数が未設定なら**ファイルは一切探されない**（シェルでexport済みの変数はそのまま使われる）。

以降の「環境ファイルに設定する」は、すべてこのファイルを指す。

### GitHub

認証は任意。未設定でも検索できるが、検索APIのレート制限が未認証10 req/min・認証済み30 req/minと大きく異なるため、トークンの発行を推奨する。

1. [Personal access token (fine-grained)](https://github.com/settings/tokens?type=beta) を発行する。公開Issueの検索のみなので、scopeは不要（`public_repo`も不要）
2. 環境ファイルに設定する（既にシェルで`GITHUB_TOKEN`をexportしている場合はそちらが優先される）

```
GITHUB_TOKEN=発行したトークンをここに貼る
```

### Reddit

認証必須。読み取り専用のapplication-only OAuth2（`client_credentials`）を使うため、ユーザーのログインは不要。

1. https://www.reddit.com/prefs/apps で「create another app...」→ **script** タイプで新規登録する（redirect URIはローカル収集では使わないため、`http://localhost` 等の適当な値でよい）
2. 登録後に表示される `client_id`（アプリ名の下の文字列）と `secret` を控える
3. 環境ファイルに設定する

```
REDDIT_CLIENT_ID=xxxxxxxxxxxxxxxx
REDDIT_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# RedditのAPIルール上、固有かつ説明的な文字列が必須。既定のUAは遮断される
# 書式: <platform>:<app id>:<version> (by /u/<あなたのRedditユーザー名>)
REDDIT_USER_AGENT=script:sns-collector:1.0 (by /u/yourname)
```

### YouTube

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成（または既存プロジェクトを使用）
   - **課金アカウントの紐付けは不要**。YouTube Data API v3は1日10,000ユニットまで無料で、有料枠が存在しない（上限に達すると翌日まで停止するだけで課金は発生しない）
2. 「APIとサービス」→「ライブラリ」から **YouTube Data API v3** を有効化
   - 名前の似た`YouTube Analytics API` / `YouTube Reporting API`は別物。**v3**を選ぶこと
3. 「認証情報」→「認証情報を作成」→「APIキー」でキーを発行
4. **発行したキーを制限する**（次節。省略しないこと）
5. 環境ファイルにキーを設定する

```
YOUTUBE_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**このリポジトリはPublicであり、鍵はリポジトリの外に置いてもなお漏れうる。** キーの制限設定は事故時の被害を限定するための最後の防壁になる。

#### APIキーの制限

発行したキーの「キーを制限」（鉛筆アイコン）を開く。

**APIの制限** — 必ず設定する。

- 「キーを制限」を選択し、`YouTube Data API v3` **のみ**にチェックを入れる

これにより、キーが漏洩しても他のGoogle APIには使用できなくなる。

**アプリケーションの制限** — ローカルcron実行では設定が難しい。

| 選択肢 | 適否 |
|---|---|
| なし | 実用上これを選ぶことになる |
| IPアドレス | 固定IPなら有効。動的IPだと変わるたびにキーが使えなくなる |
| HTTPリファラー / Androidアプリ / iOSアプリ | サーバー・CLIからの呼び出しには使えない |

固定IPでなければ「なし」でよい。**APIの制限さえ掛けておけば実害はほぼ抑えられる**（このキーで読めるのはYouTubeの公開検索データのみで、書き込み権限もない）。

#### 動作確認とトラブルシュート

```sh
uv run sns-collector youtube
```

9キーワード分が出力されれば成功。**この1回で900ユニット**（1日10,000のうち9%）を消費する。

| 症状 | 原因 |
|---|---|
| `設定エラー: 必須の環境変数 YOUTUBE_API_KEY が未設定です` | `SNS_COLLECTOR_ENV_FILE`が未設定、または変数名が違う |
| `設定エラー: SNS_COLLECTOR_ENV_FILE が指すファイルがありません` | 指定先へ環境ファイルを置いていない（探索へは落ちない） |
| 全キーワードで`403 Client Error` | APIの制限が誤っている、またはAPI未有効化 |
| 途中から`403` | クォータ超過（太平洋時間0時にリセット） |

`403`は再試行対象のため、3回リトライしてからスキップされ、run末尾に失敗キーワード一覧が出る。全件失敗ならキー側の問題である。

消費状況は「APIとサービス」→「YouTube Data API v3」→「割り当てと上限」で確認できる。

## 検索キーワードの編集

`config/keywords.yaml`を編集する。プラットフォームごとに独立したキーワードリストを持ち、**役割が異なる**。

- **Bluesky・Hacker News・GitHub・Reddit = 需要シグナル**。投稿本文・コメント・Issue・スレッドを検索し、未充足ニーズや不満の生の表現を拾う
- **YouTube = 供給シグナル**。動画のタイトル・説明文しか検索できないため、痛みを表す語（「面倒」「使いにくい」等）はほぼヒットしない。既存ソリューション・競合・市場の関心度の測定に用途を限定する
- **hnjobs = 金の流れシグナル**（ADR-0010）。Hacker Newsの月次求人・案件スレッドから、企業・発注者が実際に予算を付けている領域を測る。**求人票に困りごと表現は含まれない。** 痛みを表す語を投げないこと

観測対象ドメインとその仮説は`config/domains.yaml`に定義する。設計の背景は`docs/requirements.md`を参照。

```yaml
bluesky:
  sort: latest # latest | top
  limit_per_keyword: 50
  keywords:
    - "ラズパイ YOLO"

youtube:
  order: relevance # relevance | date | rating | viewCount
  max_results_per_keyword: 25
  region_code: JP
  relevance_language: ja
  keywords:
    - "Jetson YOLO"

hackernews:
  tags: "(story,comment)" # Algoliaのタグフィルタ(括弧が無いとAND判定になり常に0件)
  hits_per_page: 50
  keywords:
    - '"jetson nano"'

github:
  qualifiers: "is:issue" # 外すとPull Requestも混ざる
  per_page: 50
  keywords:
    - "onnx conversion error"

reddit:
  sort: new # new | relevance | top | comments
  time_filter: month # hour | day | week | month | year | all
  limit_per_keyword: 50
  keywords:
    - "jetson inference slow"

hnjobs:
  thread_kinds: ["hiring", "freelancer"] # hired(求職)は金を出す側ではないため既定で採らない
  thread_limit: 3 # 種別ごとの遡り月数
  hits_per_page: 50
  keywords:
    - '"embedded"'
```

`hnjobs`だけは検索の当て方が違う。**キーワードで全文検索するのではなく、月次スレッドを特定してからその中を検索する。** 主催アカウントでスレッドを引き、タイトルで種別（求人 / 案件 / 求職）を分け、スレッド直下のコメントだけを求人票として採る。返信は議論なので採らない。

**`hnjobs`のキーワードは事前確認のみ済み**（2026-08-11、検索APIで求人3本・案件3本へ問い合わせ）。収集データでの検証は初回収集後に行う。試し打ちには`sns_collector.adapter.source.hnjobs.client.list_threads` / `search_thread`を使う（認証不要・DB非破壊）。**その際、Algoliaの既定のタイプミス吸収を切ること**（`typoTolerance=false`）。切らないと短い語が別語へ広がり、`"cnc"`が13件ヒットして中身は全て無関係、という形の誤検知が出る。収集側（`adapter/source/hnjobs/client.py`）では無効化済み。

**Redditのキーワードはまだ検証していない。** 他プラットフォームと同様、`sns_collector.adapter.source.reddit.client.search_posts`（トークン取得が要るため`sns_collector.adapter.source.reddit.auth.fetch_token`と組み合わせる）でDB非破壊に試し打ちし、キーワード設計の3原則（下記）に照らして確認してから`cron_run.sh`へ登録すること。

**GitHubのキーワードには、他プラットフォームに無い制約が2つある**（2026-08-11の事前確認で判明。詳細と実測値は`config/keywords.yaml`の改訂履歴）。

1. **`org:` / `repo:` で必ず限定する。** 限定しない検索はAI生成のダイジェストリポジトリが支配する（無限定の`ros2 "hard to debug"`は30件中26件が単一リポジトリだった）
2. **取得件数ではなく母集団（`total_count`）で判定する。** `per_page`の上限まで常に返るため、フレーズ絞り込みが効いていても件数は張り付いて見分けが付かない。目安は20〜300件

試し打ちには`sns_collector.adapter.source.github.client.search_issues`を使う（トークン未設定でも動く）。`total_count`が要るときは`adapter/http.py::get_json`で直接叩く。

### キーワード設計の3原則

すべて実測で確認したもの（原則1・2は2026-07-29の日本語、原則3は2026-08-02の英語）。日本語では**取得件数が多いキーワードほどノイズである**という傾向がはっきり出ている。原則3のとおり、これは英語では成立しない。

#### 原則1: 固有名詞・技術用語のアンカーを必ず含める

Bluesky検索は日本語のスペース区切りを厳密なANDとして扱わず、部分一致も発生する。日本語には語境界がないため、`精度` `難しい` `足りない` のような一般語だけを組み合わせるとノイズが支配的になる。

| キーワード | 取得 | 実際にヒットした内容 |
|---|---|---|
| `量子化 精度` | 50件 | 中国語の**量子化学**（`量子化`が`量子化學`に部分一致） |
| `GPU メモリ 足りない` | 50件 | VRゲーム、AI投資の話題 |
| `エッジAI 難しい` | 46件 | 「音楽理論を学ぶのが難しい」 |
| `パラレルリンク` | 23件 | **遊戯王**のカード（機構用語との同名衝突） |
| `課金してでも` | 50件 | ソシャゲのガチャ課金 |

#### 原則2: 英字の固有名詞には必ず日本語の語を添える

**日本語圏を狙うキーワードにのみ適用する。** 英語圏を狙うものは、この原則の対象外である（狙って英字のみにする）。

英字のみのキーワードは、英語圏の投稿・公式アカウントの宣伝・bot投稿を拾い、日本語圏の生の声が取れない。

| キーワード | 取得 | 実際にヒットした内容 |
|---|---|---|
| `Ultralytics` | 50件 | 同社公式アカウントの**採用告知** |
| `OpenVINO` | 50件 | GitHubトレンド**bot** |
| `ONNX Runtime` | 43件 | **スペイン語**の技術記事 |
| `Jetson Orin` | 48件 | 英語圏（NVIDIA値上げの話題） |

対して、日本語を伴うものは少数でも的確だった。

| キーワード | 取得 | 実際にヒットした内容 |
|---|---|---|
| `ラズパイ YOLO` | 5件 | 「ラズパイでYoloを動かすために何度OSごと書き換えたことか」 |
| `3Dプリンタ 造形失敗` | 20件 | 「Bambu Lab A1を使って分かった。失敗する原因と対策」 |
| `Jetson 動かない` | 4件 | Jetson系ボードの実機トラブル |
| `TensorRT 変換` | 4件 | ONNX→TensorRT変換のエラー解説 |

#### 原則3: 英語では取得件数が質のシグナルにならない

日本語のノイズは、語境界が無いことによる部分一致だった（`量子化` が `量子化學` に一致する）。件数に比例して増えるため「50件＝ノイズ」が判定材料になった。英語には語境界があり同種の衝突が起きにくいため、この判定は使えない。

**英語のノイズはアカウントの種別に宿る。** 上位アカウントの偏りを見ること。

| キーワード | 取得 | 上位アカウントの内訳 | 判定 |
|---|---|---|---|
| `3d print failed` | 50件 | 最大2件/アカウント。分散 | ◎ 生の声が支配 |
| `resin print failed` | 48件 | 最大2件/アカウント。分散 | ◎ |
| `cuda out of memory` | 50件 | HuggingFaceフォーラムのブリッジが23件 | ✗ |
| `class imbalance dataset` | 50件 | arXiv論文botが12件 | ✗ |
| `edge device inference` | 49件 | `arxiv-daily-bot` が7件 | ✗ |
| `gimbal diy` | 25件 | DJI規制のニュースbotが6件 | ✗ |

ノイズを出していた種別は次の3つ。

- `*.web.brid.gy` / `*.ap.brid.gy` — HuggingFaceフォーラム・ActivityPubからのブリッジ投稿
- `*-bot.bsky.social` — arXiv論文の自動投稿（`cscv-bot`、`cslg-bot` 等）
- 技術ニュースの自動投稿（`aichina.news`、`spacefeed` 等）

**上限に達していない件数で質を判断してはならない。** issue #12 は `inference too expensive` を上限25件で観測して有望としたが、50件で引き直すと推論コストの相場ニュースとRTが支配的だった。

#### 原則1・2はBluesky固有である

YouTube側は2026-07-29の実測で9キーワードすべてが的確であり、原則1・原則2の問題は発現しなかった。Googleの関連度ランキングが日本語でも有効に働くためである。

**同一の語でもプラットフォームによって結果が根本的に異なる。**

| 語 | Bluesky | YouTube |
|---|---|---|
| パラレルリンク | 遊戯王のカード（23件）✗ | FANUC M-2iA、山洋電気の産業機 ◎ |

**キーワードは必ずプラットフォーム別に検証すること。**

また、**YouTubeでは取得件数が質のシグナルにならない**。関連度順で常に`maxResults`まで返るため、全キーワードが一律25件になる。Blueskyで有効だった「50件＝ノイズ」という判定材料はここでは使えないため、必ずタイトル・説明文をサンプリングして確認する。

#### 運用

**キーワードの役割は「領域を絞る」ことに徹させ、痛みかどうかの判定は後段の構造化抽出に委ねる。**

同名衝突がある語には限定語を添えること。実測では`パラレルリンク`（23件・遊戯王）を`パラレルリンク 機構`にすると1件になり、ノイズが消滅した。`STL`（C++標準ライブラリと衝突）→`STLデータ`、`量子化`（中国語の量子化学と衝突）→`量子化 INT8`も同様。

キーワードを追加・変更したら実データをサンプリングして質を確認し、`config/keywords.yaml`の改訂履歴に根拠を残すこと。

質の確認（キーワード単位の件数・困りごと表現を含む割合の代理指標）は以下で集計できる。

```sh
uv run sns-collector keywords quality --platform bluesky
```

**これは正式な判定ではない。** 正規表現による粗い代理指標であり、`insight_type` / `pain_level` の確定判定は構造化抽出（`extract prepare` → Claude Codeセッション → `extract load`）に委ねる。キーワードの採否を判断する前段の目安として使うこと。

## 手動実行

```sh
uv run sns-collector bluesky
uv run sns-collector youtube
uv run sns-collector hackernews
uv run sns-collector github
uv run sns-collector reddit
uv run sns-collector hnjobs
```

## 分析ストア（DuckDB）

収集した投稿は `data/analysis.duckdb` に取り込まれ、SQLで横断検索できる。DuckDBは組み込み型なのでサーバの起動は要らない（ADR-0001）。

```sh
uv run sns-collector db init            # スキーマ作成・更新
uv run sns-collector db load            # 収集済みJSONLを取り込む(冪等)
uv run sns-collector db load --since 2026-08-01
```

**収集コマンドはDBへ直接書き込む。** 通常運用で `db load` を回す必要はない。使うのは次の場合である。

- DBを削除・破損させたあと、JSONLから作り直すとき
- 別マシンで収集したJSONLを取り込むとき
- アダプタを直したあと、過去分に反映するとき

`db load` は何度実行しても結果が変わらない。同じ投稿が複数キーワードで見つかった場合、`matched_keywords` に和集合として足される。

### 重複排除はDBが持つ

以前は `state/{platform}_seen.json`（SeenStore）が既知IDを持ち、60日で捨てていた。現在は `posts` の主キーに一本化してある（ADR-0004）。全期間の投稿IDを保持するため、61日後に同じ投稿を取り直すことがなくなった。

**移行手順**（SeenStoreを使っていた環境のみ）:

```sh
uv run sns-collector db load    # 収集済みJSONLをDBへ入れる
rm state/bluesky_seen.json state/youtube_seen.json
```

JSONLに残っている投稿はすべてDBへ入るため、SeenStoreを読み直す必要はない。ロード後にSeenStoreを消しても、既知判定は失われない。

### 構造化抽出

投稿から「未充足ニーズ／不満」を構造化して `insights` へ入れる。パイプラインからLLMは呼ばず、バッチファイルの受け渡しでClaude Codeセッションが担う（ADR-0003）。

```sh
uv run sns-collector extract prepare --limit 20   # バッチと作業指示を書き出す
# → Claude Codeセッションで <batch-id>.md を読ませて実行
uv run sns-collector extract load <batch-id>      # 検証してDBへ
uv run sns-collector extract status               # 待ち件数・未取り込みバッチ
```

**対象は既定でBluesky・Hacker Newsのみ。** `github` / `hnjobs` / `reddit` は
`--platform` の明示指定でしか載らない（ADR-0009・ADR-0010）。**新しいドメインを
domains.yaml へ足しても、対象プラットフォームを指定しなければ抽出は始まらない。**
例: `uv run sns-collector extract prepare --platform github --limit 10`。
GitHub Issueは本文が長いため（中央値1,585字・最大47k字）、`--limit` を小さく取ること。 YouTubeは供給シグナルであり、動画メタデータへ需要シグナルの抽出を掛けてもほぼ `none` にしかならない。

取り出す順は収集日の新しい順。投稿日の古い順だと、初回収集で遡った2009年の動画から処理することになる。

抽出プロンプトは `prompts/extract-v2.md`（既定）。バージョンは `insights.extractor_version` に記録され、`--version` で切り替える。改訂したら新しい版として足し、既存の版は消さない（どの版で抽出したかを後から辿るため）。

プロンプトを改訂したら、旧版で抽出した投稿を取り直せる。

```sh
uv run sns-collector extract prepare --reextract v1   # v1で抽出済みを pending へ戻して選ぶ
```

旧版の `insights` は消さない。新版で取り込んだときに上書きされるため、途中で中断しても結果が残る。

**検証を通らなかった行は `<batch-id>.errors.jsonl` へ隔離され、該当投稿は `batched` のまま残る。** 次回の `prepare` では拾われないので、再抽出するには結果ファイルを直して `load` をやり直す。

### 埋め込みと意味検索

`insights.summary` をベクトル化し、表記揺れを跨いだ自然言語検索を可能にする（F-10, F-11）。埋め込みはローカルモデル（`fastembed` / ONNX Runtime）で生成し、外部APIは呼ばない（ADR-0002）。

```sh
uv run sns-collector embed --limit 500          # 未埋め込みのsummaryをベクトル化
uv run sns-collector search "決済まわりの不満"    # 意味検索
uv run sns-collector search "推論が遅い" --type complaint --pain-level 3 --monetizable true
uv run sns-collector search "セットアップ" --platform bluesky --since 2026-08-01 --text YOLO
```

`search` は意味検索・構造化絞り込み（`--type` / `--domain` / `--pain-level` / `--monetizable` / `--platform` / `--since`）・全文検索（`--text`）を1本のSQLで合成する。`insights.embedding` が無い行（未埋め込み）はヒットしない。

**モデルは `intfloat/multilingual-e5-large`（次元1024, MIT）を採用した。** 選定は実データによる比較で行った。根拠と比較結果はADR-0002を参照。

**近似最近傍インデックス（HNSW）は導入していない。** DuckDB VSS拡張のHNSWは固定長ベクトル型（`FLOAT[N]`）のみ対応し、可変長の `insights.embedding`（`FLOAT[]`）には張れない。総当たりの `list_cosine_similarity` で実測したところ、10万行・1024次元でも0.36秒であり、design.md §5.3の想定規模では十分実用的なため、意図的に採用していない。コーパスが増えて実測上遅くなったら見直す。

**モデルを変更する場合**、既存の埋め込みと新しいモデルのベクトルが混在すると `list_cosine_similarity` が壊れる。切り替える前に全件をリセットしてから `embed` をやり直す。

リセットを忘れた場合は `embed` と `search` が実行前に拒否する（`embed.ensure_model_matches`）。**手順の記憶に頼らせない。** 混在させてしまうと `search` が例外で落ちるだけで、どの行が古いモデルなのかは表示されない。

```sh
uv run python -c "
import duckdb
conn = duckdb.connect('data/analysis.duckdb')
conn.execute('UPDATE insights SET embedding = NULL, embedding_model = NULL')
"
uv run sns-collector embed --model <新しいモデル名> --limit 100000
```

### 関係グラフ

アカウント・キーワード・競合製品・ドメイン・投稿の関係を `edges` へ導出する（F-12, F-13）。専用のグラフDBは持たず、DuckDBの汎用エッジテーブルとして表現する（ADR-0001）。

```sh
uv run sns-collector graph rebuild                        # 4種すべてを再構築
uv run sns-collector graph rebuild --edge-type cooccurs --edge-type belongs_to
uv run sns-collector graph rebuild --similarity-threshold 0.9 --top-k 5
```

| edge_type | src → dst | weight |
|---|---|---|
| `mentions` | `author` → `product` | その競合製品に言及した投稿数 |
| `cooccurs` | `keyword` → `keyword` | 両方にヒットした投稿数（片方向のみ。`src < dst`） |
| `belongs_to` | `keyword` → `domain` | そのキーワードの投稿がそのドメインへ分類された件数 |
| `similar_to` | `post` → `post` | `insights.embedding` のコサイン類似度（投稿ごとに上位 `--top-k` 件で打ち切る） |

**毎回全削除してから入れ直す。** `keywords.yaml` から外したキーワードの共起や、再抽出で消えた競合言及が残り続けないよう、同じ入力からは常に同じ集合になることを優先している。再実行しても件数・内容は変わらない。

**`similar_to` は埋め込み済み件数の二乗に比例する。** 実測で2万件が目安（約5分）を超えると `graph rebuild` は実行前に拒否する。超えた場合は `--edge-type` で `similar_to` を外して他の3種だけ再構築すること。埋め込みモデルが混在している場合も同様に拒否する（`embed` の項を参照）。

クエリ例:

```sql
-- キーワード共起の上位ペア
SELECT src_id, dst_id, weight
FROM edges WHERE edge_type = 'cooccurs'
ORDER BY weight DESC LIMIT 20;

-- ある競合製品への言及元アカウント一覧
SELECT src_id AS author_id, weight AS mention_count
FROM edges WHERE edge_type = 'mentions' AND dst_id = 'Roboflow'
ORDER BY weight DESC;

-- ある投稿に似た投稿（近傍探索）
SELECT dst_id AS similar_post_id, weight AS similarity
FROM edges WHERE edge_type = 'similar_to' AND src_id = 'bluesky:at://...'
ORDER BY weight DESC;
```

### 定期レポート

`posts` / `insights` に対する決定論的な集計のみを行い、Markdownを生成する（F-14〜F-16）。LLMを呼ばないため、cronで無人生成できる（F-15）。

```sh
uv run sns-collector report                 # 直近7日分
uv run sns-collector report --since 14d      # 直近14日分
uv run sns-collector report --top-n 20       # 頻出キーワード等の上位件数を変える
```

`reports/report-<since>_<until>.md`（例: `reports/report-2026-08-01_2026-08-08.md`）へ書き出す。**同じ期間で再実行すると同じファイルへ上書きする。** 秒単位のIDを持たせないのは、cronの日次実行のたびにファイルが増え続けるのを避けるため。

出力内容:

- 期間内の新規観測件数（プラットフォーム別・日次）
- `insight_type` 別の分布（代表投稿つき）
- `domain` 別の件数と前期間比
- `pain_level=3` かつ `monetizable=true` の投稿の全件リスト（最重要シグナル。件数の上限は無い）
- 頻出キーワードと共起ペア上位
- 新規に観測された競合製品名（過去のどの期間にも登場していなかったもの）

**`domain`・`insight_type` は `extracted_at`、新規観測件数は `collected_at`、頻出キーワードは `collected_at` を基準に期間を切る。** 抽出はバッチ運用のため投稿の収集時期とはずれる。「この期間に何を集めたか」と「この期間に何を抽出して分かったか」を区別するため、集計の基準時刻をセクションごとに変えている。

**洞察・仮説の加筆（F-16）はここでは行わない。** 生成されたMarkdownを入力に、`prompts/report-insights.md` の作業指示に従ってClaude Codeセッションで追記する。加筆結果は同じファイルへ上書きする（定量部分と洞察部分を1つのレポートとして残す）。

**潜在的な事業機会の抽出（任意）。** `monetizable=true`の明示的な表現とは別に、「既存製品の具体的な機能欠落」×「小規模開発で埋められそうか」という軸で候補を拾いたい場合は、`prompts/opportunity-gap.md` の作業指示に従ってClaude Codeセッションで実行する。こちらもレポートへの追記であり、パイプラインからの自動実行はしない（ADR-0003。ヘッドレスモードでの自動化も同じ理由で対象外）。

### バックアップ

DBは単一ファイルなので、コピーで完結する（N-07）。

```sh
cp data/analysis.duckdb data/analysis.duckdb.$(date +%Y%m%d)
```

生JSONLが残っている限りDBは作り直せるが、Phase 2以降に入る抽出結果（`insights`）はClaude Codeセッションを使って生成するため、失うと再生成にコストがかかる。週次でのバックアップを推奨する。

### 収集済みデータのフィールドについて

`author_did` / `lang` / `raw` は2026-08-02に追加した。それ以前に収集したJSONLにこれらは無く、DB上では `NULL` になる。過去分は取り直せない（Blueskyの検索は最新のインデックスしか返さない）。

## 出力

`data/{bluesky,youtube,hackernews,hnjobs,github,reddit}/<YYYY-MM-DD>.jsonl`に1行1JSONで追記される（同日内の複数回実行は同一ファイルに追記）。

run跨ぎの重複を避けるため、収集した投稿は同時に`data/analysis.duckdb`の`posts`へ書き込まれ、次回以降はそこを既知判定に使う（[分析ストア](#分析ストアduckdb)を参照）。同じキーワードで再実行しても、既に収集済みの投稿・動画は再度JSONLに書き込まれない。

既知の投稿が別のキーワードでも見つかった場合、JSONLには書かれないが`posts.matched_keywords`へその語が追加される。どの語が効いているかはキーワード改訂の判断材料になる。

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
# Hacker Newsキーワード検索(3時間おき、他の2つと30分ずらして負荷分散)
30 */3 * * * /path/to/marketing-data-pipeline/sns-collector/scripts/cron_run.sh hackernews
# 定期レポート(週次、月曜9時。collectorと重ならない時間を選ぶ)
0 9 * * 1 /path/to/marketing-data-pipeline/sns-collector/scripts/cron_run.sh report
```

実行ログは`state/.logs/{bluesky,youtube,hackernews,report}.log`に記録される。

**`extract` / `embed` / `graph rebuild` はcronに登録しない。** 抽出はClaude Codeセッションを要する手動運用（[構造化抽出](#構造化抽出)）、埋め込みとグラフ再構築は抽出結果に依存するため、抽出のたびに手動で回す。週次運用の手順は次の通り。

1. `uv run sns-collector extract prepare` でバッチを作り、Claude Codeセッションで抽出する
2. `uv run sns-collector extract load <batch-id>` で取り込む
3. `uv run sns-collector embed` で新しく増えた `summary` を埋め込む
4. `uv run sns-collector graph rebuild` でエッジを最新化する（省略可。`similar_to` を使わないなら必須ではない）
5. `uv run sns-collector report` は週次cronが自動生成する。生成後、`prompts/report-insights.md` の作業指示に従ってClaude Codeセッションで洞察を加筆する

### YouTubeのクオータと実行頻度

`search.list`は1回100クオータユニットを消費し、1日の無料枠は10,000ユニット。

```
1日あたりの実行可能回数 ≈ 10000 / (100 × keywords件数)
```

例えばキーワードが3件なら、1日あたり最大約33回まで実行可能。`config/keywords.yaml`のキーワード数とcronの実行頻度のバランスはこの式を目安に調整すること。

## レート制限とエラー耐性

キーワード数が増えるとAPI側のスロットリングに掛かるため、`adapter/http.py`が全HTTPリクエストを仲介する。

- **ペーシング**: 1リクエストごとに1秒の間隔を空ける
- **再試行**: `403 / 429 / 5xx`を一時的な障害とみなし、指数バックオフ（2秒→4秒→8秒）で最大3回まで再試行する。`Retry-After`ヘッダがあればその値を優先する
  - Blueskyは連続アクセス時のスロットリングを`429`ではなく`403`で返すことがあるため、`403`も再試行対象に含めている
- **キーワード単位の隔離**: 再試行しても回復しないキーワードはスキップして次へ進む。**1キーワードの失敗でrun全体を落とさない**

**GitHubの検索APIだけレート制限が桁違いに低い**（未認証10 req/min・認証済み30 req/min）。他プラットフォームの1秒間隔ではなく、`adapter/source/github/client.py`が独自に6.5秒（未認証）/2.5秒（認証済み）の間隔を空ける。**Redditはトークン取得（POST）にも同じペーシング・再試行の仕組み（`adapter/http.py::post_json`）を通す。**

最後の点が重要である。収集結果の保存はループ完了後に一度だけ行われるため、途中で例外が送出されるとそれまでに収集した全件が破棄される。特にYouTubeでは、消費済みのクオータまで無駄になる。

取りこぼしたキーワードはrun末尾に一覧表示され、次回の定期実行でカバーされる（1キーワード1ページのみ取得し、定期実行でカバレッジを積み上げる設計と整合する）。

## テスト

```sh
uv run pytest
```

実際のAPI通信は行わず、`requests`をモックした単体テストのみ。

## 制約・注意事項（MVPスコープ外）

- YouTubeのコメント取得（動画メタデータのみ）
- GitHub Actions等クラウド上での自動実行（リポジトリがPublicであり、収集データを非公開に保つためローカルcronのみをサポート）
- 検索結果のページング（1キーワード1ページのみ取得。定期実行によって自然にカバレッジが積み上がる設計）
- ログローテーション（`state/.logs/`配下は定期的に手動で確認・削除すること）
