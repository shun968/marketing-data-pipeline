from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from sns_collector.db import connect
from sns_collector.search import search


def _fake_embedder(vector):
    return lambda texts: [vector for _ in texts]


def _insert_post(conn, *, post_id, platform, url, text, posted_at) -> None:
    conn.execute(
        """
        INSERT INTO posts (id, platform, native_id, text, url, posted_at, extraction_status)
        VALUES (?, ?, ?, ?, ?, ?, 'done')
        """,
        [post_id, platform, post_id, text, url, posted_at],
    )


# 実際の embed() は必ず embedding_model を書く。テストで NULL のままにすると、
# ensure_model_matches が素通りする構成だけを検証することになる
MODEL = "fake-model"


def _insert_insight(
    conn,
    *,
    post_id,
    embedding,
    insight_type="complaint",
    domain="edge_ai",
    pain_level=1,
    monetizable=False,
    embedding_model=MODEL,
) -> None:
    conn.execute(
        """
        INSERT INTO insights
            (post_id, insight_type, domain, summary, pain_level, monetizable,
             embedding, embedding_model)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            post_id,
            insight_type,
            domain,
            f"summary for {post_id}",
            pain_level,
            monetizable,
            embedding,
            embedding_model if embedding is not None else None,
        ],
    )


@pytest.fixture
def conn(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as c:
        yield c


def test_類似度の高い順に返す(conn):
    _insert_post(
        conn,
        post_id="near",
        platform="bluesky",
        url="https://example.com/near",
        text="近い投稿",
        posted_at=datetime(2026, 8, 1),
    )
    _insert_post(
        conn,
        post_id="far",
        platform="bluesky",
        url="https://example.com/far",
        text="遠い投稿",
        posted_at=datetime(2026, 8, 1),
    )
    _insert_insight(conn, post_id="near", embedding=[1.0, 0.0, 0.0])
    _insert_insight(conn, post_id="far", embedding=[0.0, 1.0, 0.0])

    hits = search(conn, "クエリ", model_name=MODEL, embedder=_fake_embedder([1.0, 0.0, 0.0]))

    assert [h.post_id for h in hits] == ["near", "far"]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(0.0)


def test_埋め込み未生成の行はヒットしない(conn):
    _insert_post(
        conn,
        post_id="no-embedding",
        platform="bluesky",
        url="https://example.com/x",
        text="投稿",
        posted_at=datetime(2026, 8, 1),
    )
    conn.execute(
        "INSERT INTO insights (post_id, insight_type, domain, summary) "
        "VALUES ('no-embedding', 'complaint', 'edge_ai', '要約')"
    )

    hits = search(conn, "クエリ", model_name=MODEL, embedder=_fake_embedder([1.0, 0.0, 0.0]))

    assert hits == []


@pytest.mark.parametrize(
    ("filters", "理由"),
    [
        ({"insight_type": "feature_request"}, "insight_typeが一致しない"),
        ({"domain": "fabrication"}, "domainが一致しない"),
        ({"pain_level": 3}, "pain_levelが一致しない"),
        ({"monetizable": True}, "monetizableが一致しない"),
        ({"platform": "youtube"}, "platformが一致しない"),
        ({"since": date(2026, 8, 2)}, "posted_atがsinceより前"),
        ({"text": "無関係"}, "本文に部分一致しない"),
    ],
)
def test_絞り込み条件に一致しなければ除外する(conn, filters, 理由):
    _insert_post(
        conn,
        post_id="p1",
        platform="bluesky",
        url="https://example.com/p1",
        text="ラズパイでYOLOが動かない",
        posted_at=datetime(2026, 8, 1),
    )
    _insert_insight(
        conn,
        post_id="p1",
        embedding=[1.0, 0.0, 0.0],
        insight_type="complaint",
        domain="edge_ai",
        pain_level=2,
        monetizable=False,
    )

    hits = search(
        conn, "クエリ", model_name=MODEL, embedder=_fake_embedder([1.0, 0.0, 0.0]), **filters
    )

    assert hits == [], 理由


def test_絞り込み条件に一致すれば含める(conn):
    _insert_post(
        conn,
        post_id="p1",
        platform="bluesky",
        url="https://example.com/p1",
        text="ラズパイでYOLOが動かない",
        posted_at=datetime(2026, 8, 1),
    )
    _insert_insight(
        conn,
        post_id="p1",
        embedding=[1.0, 0.0, 0.0],
        insight_type="complaint",
        domain="edge_ai",
        pain_level=2,
        monetizable=False,
    )

    hits = search(
        conn,
        "クエリ",
        model_name=MODEL,
        embedder=_fake_embedder([1.0, 0.0, 0.0]),
        insight_type="complaint",
        domain="edge_ai",
        pain_level=2,
        monetizable=False,
        platform="bluesky",
        since=date(2026, 7, 1),
        text="YOLO",
    )

    assert [h.post_id for h in hits] == ["p1"]


def test_コーパスと違うモデルを指定したら一行のエラーにする(conn):
    """duckdbのInvalidInputExceptionはcli.pyのどのハンドラにも掛からない。

    素のトレースバックを出さず、直し方の分かるValueErrorへ変換する。
    """
    _insert_post(
        conn,
        post_id="a",
        platform="bluesky",
        url="https://example.com/a",
        text="投稿",
        posted_at=datetime(2026, 8, 1),
    )
    _insert_insight(conn, post_id="a", embedding=[1.0, 0.0, 0.0])
    conn.execute("UPDATE insights SET embedding_model = 'model-a'")

    with pytest.raises(ValueError, match="model-a"):
        search(conn, "クエリ", model_name="model-b", embedder=_fake_embedder([1.0, 0.0]))


def test_コーパスと同じモデルなら検索できる(conn):
    """誤検知しないこと。"""
    _insert_post(
        conn,
        post_id="a",
        platform="bluesky",
        url="https://example.com/a",
        text="投稿",
        posted_at=datetime(2026, 8, 1),
    )
    _insert_insight(conn, post_id="a", embedding=[1.0, 0.0, 0.0])
    conn.execute("UPDATE insights SET embedding_model = 'model-a'")

    hits = search(conn, "クエリ", model_name="model-a", embedder=_fake_embedder([1.0, 0.0, 0.0]))
    assert [h.post_id for h in hits] == ["a"]
