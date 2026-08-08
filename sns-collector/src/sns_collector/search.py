"""意味検索（F-09〜F-11）。

意味検索・構造化絞り込み・全文検索を1本のSQLで合成する（design.md §4.5）。
DuckDBが3種を同一クエリ内で扱えることが採用理由の1つ（ADR-0001）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from .embed import DEFAULT_MODEL, Embedder, embed_query, ensure_model_matches

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb


@dataclass(frozen=True)
class SearchHit:
    post_id: str
    platform: str
    url: str | None
    summary: str | None
    insight_type: str
    domain: str | None
    pain_level: int | None
    monetizable: bool | None
    score: float


def search(
    conn: duckdb.DuckDBPyConnection,
    query: str,
    *,
    embedder: Embedder | None = None,
    model_name: str = DEFAULT_MODEL,
    insight_type: str | None = None,
    domain: str | None = None,
    pain_level: int | None = None,
    monetizable: bool | None = None,
    platform: str | None = None,
    since: date | None = None,
    text: str | None = None,
    limit: int = 20,
) -> list[SearchHit]:
    """自然言語クエリで `insights` を検索する。

    埋め込みが無い行（`insights.embedding IS NULL`）はヒットしない。
    クエリは `insights.embedding` と同じモデルで埋め込む必要がある
    （ADR-0002: モデルを変えた場合は全件の再埋め込みが要る）。

    **モデルの照合は埋め込みを作る前に行う。** 実モデルの構築は数十秒かかり、
    どうせ落ちるものを待たせない。
    """
    ensure_model_matches(conn, model_name)

    query_vector = embed_query(query, model_name=model_name, embedder=embedder)

    conditions = ["i.embedding IS NOT NULL"]
    params: list[object] = [query_vector]

    if insight_type is not None:
        conditions.append("i.insight_type = ?")
        params.append(insight_type)
    if domain is not None:
        conditions.append("i.domain = ?")
        params.append(domain)
    if pain_level is not None:
        conditions.append("i.pain_level = ?")
        params.append(pain_level)
    if monetizable is not None:
        conditions.append("i.monetizable = ?")
        params.append(monetizable)
    if platform is not None:
        conditions.append("p.platform = ?")
        params.append(platform)
    if since is not None:
        conditions.append("p.posted_at >= ?")
        params.append(since)
    if text is not None:
        conditions.append("p.text ILIKE ?")
        params.append(f"%{text}%")

    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT
            i.post_id, p.platform, p.url, i.summary, i.insight_type, i.domain,
            i.pain_level, i.monetizable,
            list_cosine_similarity(i.embedding, ?) AS score
        FROM insights i
        JOIN posts p ON p.id = i.post_id
        WHERE {" AND ".join(conditions)}
        ORDER BY score DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [
        SearchHit(
            post_id=r[0],
            platform=r[1],
            url=r[2],
            summary=r[3],
            insight_type=r[4],
            domain=r[5],
            pain_level=r[6],
            monetizable=r[7],
            score=r[8],
        )
        for r in rows
    ]
