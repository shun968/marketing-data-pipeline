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


def corpus_dimensions(conn: duckdb.DuckDBPyConnection) -> set[int]:
    """既存の埋め込みのベクトル次元の集合。埋め込みが無ければ空。

    **守りたい不変条件はモデル名ではなく次元である。** モデル名は代理でしかなく、
    同じ名前のまま次元が変わる経路（モデルカードの更新、`embedder` を注入する
    呼び出し）では名前の照合が素通りする。DBに入っている値から直接見る。
    """
    rows = conn.execute(
        "SELECT DISTINCT len(embedding) FROM insights WHERE embedding IS NOT NULL"
    ).fetchall()
    return {r[0] for r in rows}


def resolve_model(conn: duckdb.DuckDBPyConnection, requested: str | None) -> str:
    """使うモデル名を決める。指定が無ければコーパスから引く。

    **正しいモデル名を人に覚えさせない。** 既定を `DEFAULT_MODEL` 固定にすると、
    モデルを変えた後は `--model` を毎回打ち直すまで `embed` も `search` も
    失敗し続ける（READMEのモデル変更手順どおりに進めた人がそのまま詰まる）。
    コーパスのモデルはDBから分かるので、指定が無いときはそれを採用する。

    指定があれば照合は従来どおり行う。「間違ったモデルでの検索を止める」目的は
    変えていない。
    """
    if requested is not None:
        return requested

    models = corpus_models(conn)
    if not models:
        return DEFAULT_MODEL
    if len(models) == 1:
        only = next(iter(models))
        if only is not None:
            return only

    # 混在・モデル名不明は、既定を選ぶと誤ったモデルで埋め込みを増やす。
    # ここでは決めず、下の照合と同じ文言で止める
    raise ValueError(
        f"既存の埋め込みのモデル（{_format_models(models)}）から1つに定まらない。"
        f"--model で明示するか、{_RESET_HINT}"
    )


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
    if models and models != {model_name}:
        found = _format_models(models)
        raise ValueError(
            f"既存の埋め込みのモデル（{found}）が {model_name} と一致しない。"
            f"次元が異なると検索が落ちる。同じモデルを指定するか、{_RESET_HINT}"
        )

    # モデル名が揃っていても次元が揃っているとは限らない。
    # 同じ名前で次元の違うベクトルが混ざったDBは、名前の照合を通り抜けて
    # search で素の InvalidInputException になる。**名前ではなく実物を見る。**
    dimensions = corpus_dimensions(conn)
    if len(dimensions) > 1:
        found = ", ".join(str(d) for d in sorted(dimensions))
        raise ValueError(
            f"既存の埋め込みに次元の異なるベクトルが混ざっている（{found}）。"
            f"モデル名が同じでも検索が落ちる。{_RESET_HINT}"
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

    # **混在を作る側でも止める。** 検査を読み取り時だけに置くと、壊れたDBを
    # 作ることは防げず「後から気づいて全部捨てる」しかなくなる。
    # 既存と次元が違うベクトルは書く前に弾く（embedder注入や、同名モデルの
    # 次元変更がここを通る）
    existing = corpus_dimensions(conn)
    if dimension is not None and existing and dimension not in existing:
        found = ", ".join(str(d) for d in sorted(existing))
        raise ValueError(
            f"生成したベクトルの次元（{dimension}）が既存（{found}）と違う。"
            f"混在させると検索が落ちるため書き込まない。{_RESET_HINT}"
        )

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


def reset_vectors(conn: duckdb.DuckDBPyConnection) -> int:
    """全ての埋め込みとモデル名を捨てる。捨てた件数を返す。

    **手書きSQLの写経をやめるための口である。** モデル名が不明な行が1件でも
    あると `embed` はどのモデル名でも拒否するため、そのDBは `embed` では
    直せない（対象は `embedding IS NULL` の行だけで、名前を入れ直す経路が無い）。
    出口はREADMEの `UPDATE insights SET embedding = NULL, ...` を手で打つことだけ
    になるが、打ち間違いがそのままデータ破壊になる。

    捨てるのはベクトルとモデル名だけで、`summary` を含む抽出結果には触れない。
    再生成は `embed` を回せば済む（再抽出は不要）。
    """
    before = conn.execute("SELECT count(*) FROM insights WHERE embedding IS NOT NULL").fetchone()[0]

    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(
            "UPDATE insights SET embedding = NULL, embedding_model = NULL "
            "WHERE embedding IS NOT NULL OR embedding_model IS NOT NULL"
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return before


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
