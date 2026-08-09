"""関係グラフの導出（F-12, F-13）。

`edges` は `posts` / `insights` から導出される二次データであり、捨てて
再構築できる（design.md §3.3）。専用のグラフDBは持たない（ADR-0001）。

導出する4種:

| edge_type | src → dst | weight |
|---|---|---|
| `mentions` | `author` → `product` | その競合製品に言及した投稿数 |
| `cooccurs` | `keyword` → `keyword` | 両方にヒットした投稿数 |
| `belongs_to` | `keyword` → `domain` | そのキーワードの投稿がそのドメインへ分類された件数 |
| `similar_to` | `post` → `post` | `insights.embedding` のコサイン類似度 |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .embed import corpus_models

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# 類似ペアとみなす下限。multilingual-e5 は無関係な文でも0.7前後を返すため、
# 0.5のような直感的な値では全ペアが繋がる。**実データでの調整が要る暫定値**であり、
# `--similarity-threshold` で変えられるようにしてある（roadmap 3-5 の評価対象）。
DEFAULT_SIMILARITY_THRESHOLD = 0.85

# 1つの投稿から張る類似エッジの上限。閾値だけで絞ると、話題が集中している期間に
# 特定の投稿群が完全グラフになり、エッジ数が件数の二乗で膨らむ
DEFAULT_TOP_K = 10

# similar_to を計算する埋め込み済み件数の上限。上の実測の外挿で約5分になる点を採った。
# cronから無人で回すコマンドなので、黙って数時間走る状態を作らない
_SIMILAR_MAX_INSIGHTS = 20_000

EDGE_TYPES = ("mentions", "cooccurs", "belongs_to", "similar_to")

# 導出元。集計の形はすべて (src_id, dst_id, weight, observed_at) の4列に揃える。
#
# **observed_at に now() を使わない。** 再実行のたびに値が変わると
# 「再構築しても結果が一意」（roadmap Phase 4 完了条件）が成立せず、
# エッジが変化したのか実行しただけなのかを区別できなくなる。
# 導出元の投稿日の最大値を採れば、同じ入力からは常に同じ値になる。
_DERIVATIONS: dict[str, str] = {
    # 競合製品名は統制語彙を持たない（domains.yaml のドメイン語とは違う）。
    # 表記揺れをここで機械的に畳むと別製品を同一視しうるため、前後の空白だけ
    # 落として原文のまま節点にする
    "mentions": """
        WITH mention AS (
            SELECT
                p.author_id AS author_id,
                trim(unnest(i.competitors)) AS product,
                p.posted_at AS posted_at
            FROM insights i
            JOIN posts p ON p.id = i.post_id
            WHERE p.author_id IS NOT NULL
        )
        SELECT author_id, product, count(*), max(posted_at)
        FROM mention
        WHERE product IS NOT NULL AND length(product) > 0
        GROUP BY 1, 2
    """,
    # 無向の関係を src < dst の1方向だけで持つ。両方向を入れると
    # 共起の上位ペアを数えるときに同じ関係を二重に数える
    "cooccurs": """
        WITH kw AS (
            SELECT DISTINCT id, unnest(matched_keywords) AS keyword, posted_at
            FROM posts
        )
        SELECT a.keyword, b.keyword, count(*), max(a.posted_at)
        FROM kw a
        JOIN kw b ON a.id = b.id AND a.keyword < b.keyword
        GROUP BY 1, 2
    """,
    "belongs_to": """
        WITH kw AS (
            SELECT DISTINCT id, unnest(matched_keywords) AS keyword, posted_at
            FROM posts
        )
        SELECT kw.keyword, i.domain, count(*), max(kw.posted_at)
        FROM kw
        JOIN insights i ON i.post_id = kw.id
        WHERE i.domain IS NOT NULL
        GROUP BY 1, 2
    """,
}

_NODE_TYPES: dict[str, tuple[str, str]] = {
    "mentions": ("author", "product"),
    "cooccurs": ("keyword", "keyword"),
    "belongs_to": ("keyword", "domain"),
    "similar_to": ("post", "post"),
}

# 類似ペア。全組み合わせを走査するため件数の二乗に比例する。
# 実測（1024次元・このコンテナ）: 250件 0.05秒 / 500件 0.19秒 / 1000件 0.71秒。
# 倍増ごとに約4倍で、外挿すると2万件で約5分、10万件で約2時間になる。
#
# **`search` の総当たり（README「埋め込みと意味検索」）とは計算量が違う。**
# あちらはクエリ1本 × 全行なので10万行でも0.36秒だが、こちらは全行 × 全行。
# 同じ「総当たりで十分」の判断をここへ持ち込めない。近似最近傍インデックスも
# 使えない（VSS拡張のHNSWは固定長 `FLOAT[N]` のみで、`insights.embedding` は
# 可変長 `FLOAT[]`）。そのため件数で先に止める（`_SIMILAR_MAX_INSIGHTS`）。
#
# 上位K件は「src < dst」へ畳む前の全方向で採る。畳んでから採ると、
# IDが小さい側の近傍が構造的に落ちて上位K件が近傍の上位K件でなくなる
_SIMILAR_SQL = """
    WITH vec AS (
        SELECT post_id, embedding FROM insights WHERE embedding IS NOT NULL
    ),
    pair AS (
        SELECT * FROM (
            SELECT
                a.post_id AS src,
                b.post_id AS dst,
                list_cosine_similarity(a.embedding, b.embedding) AS sim
            FROM vec a
            JOIN vec b ON a.post_id <> b.post_id
        )
        WHERE sim >= ?
        QUALIFY row_number() OVER (PARTITION BY src ORDER BY sim DESC, dst) <= ?
    ),
    canon AS (
        SELECT least(src, dst) AS src_id, greatest(src, dst) AS dst_id, max(sim) AS sim
        FROM pair
        GROUP BY 1, 2
    )
    SELECT c.src_id, c.dst_id, c.sim, greatest(pa.posted_at, pb.posted_at)
    FROM canon c
    JOIN posts pa ON pa.id = c.src_id
    JOIN posts pb ON pb.id = c.dst_id
"""


@dataclass(frozen=True)
class RebuildResult:
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _ensure_single_model(conn: duckdb.DuckDBPyConnection) -> None:
    """埋め込みが単一モデルで揃っているか。揃っていなければ ValueError。

    次元の違うベクトルを `list_cosine_similarity` へ渡すと DuckDB が
    InvalidInputException を投げる。これは `cli.py` のどのハンドラにも掛からず
    素のトレースバックになるため、走らせる前に止める（embed.py と同じ理由）。
    """
    models = corpus_models(conn)
    if len(models) <= 1:
        return

    found = ", ".join(sorted("不明" if m is None else m for m in models))
    raise ValueError(
        f"埋め込みのモデルが混在している（{found}）。次元が異なると類似度計算が落ちる。"
        "UPDATE insights SET embedding = NULL, embedding_model = NULL; "
        "の後に埋め込み直すこと。"
    )


def _ensure_similar_is_affordable(conn: duckdb.DuckDBPyConnection) -> None:
    """similar_to の総当たりが現実的な件数か。超えていれば ValueError。

    黙って走らせると、cronの実行が数時間居座って他のコマンドを
    DuckDBのファイルロックで締め出す。件数の二乗に比例するため、
    「今日は動いたが来月は終わらない」という形で効いてくる。
    """
    count = conn.execute("SELECT count(*) FROM insights WHERE embedding IS NOT NULL").fetchone()[0]
    if count <= _SIMILAR_MAX_INSIGHTS:
        return

    raise ValueError(
        f"埋め込み済みの insights が {count}件 あり、similar_to の総当たりが"
        f"現実的な時間で終わらない（上限 {_SIMILAR_MAX_INSIGHTS}件）。"
        "--edge-type で similar_to を除いて再構築すること。"
    )


def rebuild(
    conn: duckdb.DuckDBPyConnection,
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
    edge_types: tuple[str, ...] = EDGE_TYPES,
) -> RebuildResult:
    """`edges` を導出し直す。

    **種別ごとに全削除してから入れ直す。** design.md §3.3 は `INSERT OR REPLACE`
    と書いているが、それだけでは導出元から消えた関係（`keywords.yaml` から外した
    キーワードの共起、再抽出で消えた競合言及）が残り続け、再構築のたびに
    エッジが単調増加する。同じ入力からは常に同じ集合になることを優先する。

    全体を1トランザクションにする。途中で落ちて一部の種別だけ消えた状態を残すと、
    次の実行まで「エッジが無いのか、まだ導出していないのか」が区別できなくなる。
    """
    unknown = [t for t in edge_types if t not in _NODE_TYPES]
    if unknown:
        raise ValueError(f"未知の edge_type: {', '.join(unknown)}")

    if "similar_to" in edge_types:
        _ensure_single_model(conn)
        _ensure_similar_is_affordable(conn)

    counts: dict[str, int] = {}

    conn.execute("BEGIN TRANSACTION")
    try:
        for edge_type in edge_types:
            src_type, dst_type = _NODE_TYPES[edge_type]

            if edge_type == "similar_to":
                rows = conn.execute(_SIMILAR_SQL, [similarity_threshold, top_k]).fetchall()
            else:
                rows = conn.execute(_DERIVATIONS[edge_type]).fetchall()

            conn.execute("DELETE FROM edges WHERE edge_type = ?", [edge_type])
            if rows:
                conn.executemany(
                    """
                    INSERT INTO edges
                        (src_type, src_id, dst_type, dst_id, edge_type, weight, observed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        [src_type, src_id, dst_type, dst_id, edge_type, weight, observed_at]
                        for src_id, dst_id, weight, observed_at in rows
                    ],
                )
            counts[edge_type] = len(rows)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return RebuildResult(counts=counts)
