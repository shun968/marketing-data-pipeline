"""埋め込み生成（F-10, F-11）。

`insights.summary` をベクトル化し、意味検索（`search.py`）の入力にする。
外部APIを一切呼ばず、ローカルモデル（fastembed / ONNX Runtime）で完結する（ADR-0002）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# ADR-0002: fastembedの候補モデルを実データ(insights.summary)で比較した結果、
# 意味的類似性の精度が最も明確だったモデル。
DEFAULT_MODEL = "intfloat/multilingual-e5-large"

# multilingual-e5系は非対称プレフィックス(ドキュメント側/クエリ側で異なる接頭辞)を
# 前提に学習されている。付けずに埋め込むと精度が明確に落ちる(ADR-0002)。
_PASSAGE_PREFIX = "passage: "
_QUERY_PREFIX = "query: "

Embedder = Callable[[Sequence[str]], list[list[float]]]


@dataclass(frozen=True)
class EmbedResult:
    embedded: int
    model: str
    dimension: int | None


_RESET_HINT = (
    "UPDATE insights SET embedding = NULL, embedding_model = NULL; の後に埋め込み直すこと。"
)


def _format_models(models: set[str | None]) -> str:
    """モデル名の集合を人が読める形にする。NULLは「不明」と表示する。"""
    return ", ".join(sorted("不明" if m is None else m for m in models))


def corpus_models(conn: duckdb.DuckDBPyConnection) -> set[str | None]:
    """既存の埋め込みが使っているモデル名の集合。埋め込みが無ければ空。

    **NULL を捨てない。** `embedding_model` は migration 2 で後から足した列であり、
    ベクトルはあるのにモデル名が無い行が存在しうる。捨てると「モデルが分からない」
    が「埋め込みが無い」と同じ扱いになり、照合が素通りする。分からないものは
    分からないまま返し、判断は呼び出し側で行う。
    """
    rows = conn.execute(
        "SELECT DISTINCT embedding_model FROM insights WHERE embedding IS NOT NULL"
    ).fetchall()
    return {r[0] for r in rows}


def ensure_model_matches(conn: duckdb.DuckDBPyConnection, model_name: str) -> None:
    """要求モデルが既存コーパスと一致するか。しなければ ValueError。

    **次元の違うモデルを混ぜると search が壊れる。** `list_cosine_similarity` は
    長さの違うリストを受け取ると InvalidInputException を投げる。これは
    `cli.py` のどのハンドラにも掛からず素のトレースバックになるため、
    ここで先に止めて直し方を出す。`embedding_model` 列はこの検査のために在る。

    一致を確認できない限り通さない。モデル名が NULL の行は「別のモデルではない」
    ことを示さないため、一致とはみなさない。
    """
    models = corpus_models(conn)
    if not models or models == {model_name}:
        return

    found = _format_models(models)
    raise ValueError(
        f"既存の埋め込みのモデル（{found}）が {model_name} と一致しない。"
        f"次元が異なると検索が落ちる。同じモデルを指定するか、{_RESET_HINT}"
    )


def _default_embedder(model_name: str) -> Embedder:
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=model_name)

    def _embed(texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in model.embed(list(texts))]

    return _embed


def embed(
    conn: duckdb.DuckDBPyConnection,
    *,
    limit: int,
    model_name: str = DEFAULT_MODEL,
    embedder: Embedder | None = None,
) -> EmbedResult:
    """未埋め込みの `insights.summary` をベクトル化する。

    `embedding IS NULL` の行だけが対象のため、再実行しても既存の埋め込みは
    変わらない（冪等）。`embedder` を注入しない場合のみ実モデルを構築するので、
    テストは実モデルのダウンロードなしに決定的な埋め込み関数を渡せる。
    """
    ensure_model_matches(conn, model_name)

    rows = conn.execute(
        """
        SELECT post_id, summary FROM insights
        WHERE embedding IS NULL AND summary IS NOT NULL AND length(trim(summary)) > 0
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    if not rows:
        return EmbedResult(embedded=0, model=model_name, dimension=None)

    if embedder is None:
        embedder = _default_embedder(model_name)

    post_ids = [r[0] for r in rows]
    texts = [f"{_PASSAGE_PREFIX}{r[1]}" for r in rows]
    vectors = embedder(texts)
    if len(vectors) != len(post_ids):
        raise ValueError(
            f"embedderの出力件数が入力と一致しない: 入力{len(post_ids)}件 出力{len(vectors)}件"
        )

    dimension = len(vectors[0]) if vectors else None

    # 1件でも失敗したら全件を戻す。一部だけ書き込まれた状態は、次回実行時に
    # どこまで進んだか追えなくなる(embedding IS NULLで再選択されるので実害は
    # ないが、embedding_modelとembeddingが食い違う行を作らないため)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.executemany(
            "UPDATE insights SET embedding = ?, embedding_model = ? WHERE post_id = ?",
            [[vec, model_name, pid] for vec, pid in zip(vectors, post_ids, strict=True)],
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return EmbedResult(embedded=len(post_ids), model=model_name, dimension=dimension)


def embed_query(
    query: str,
    *,
    model_name: str = DEFAULT_MODEL,
    embedder: Embedder | None = None,
) -> list[float]:
    """検索クエリを `insights.embedding` と同じ流儀（queryプレフィックス）で埋め込む。"""
    if embedder is None:
        embedder = _default_embedder(model_name)
    return embedder([f"{_QUERY_PREFIX}{query}"])[0]
