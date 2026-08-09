from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sns_collector import graph
from sns_collector.db import connect
from sns_collector.graph import rebuild

MODEL = "fake-model"


@pytest.fixture
def conn(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as c:
        yield c


def _insert_post(
    conn,
    *,
    post_id,
    platform="bluesky",
    author_id=None,
    keywords=None,
    posted_at=datetime(2026, 8, 1),
) -> None:
    conn.execute(
        """
        INSERT INTO posts
            (id, platform, native_id, author_id, text, posted_at, matched_keywords,
             extraction_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'done')
        """,
        [post_id, platform, post_id, author_id, f"text {post_id}", posted_at, keywords or []],
    )


def _insert_insight(
    conn,
    *,
    post_id,
    domain="edge_ai",
    competitors=None,
    embedding=None,
) -> None:
    conn.execute(
        """
        INSERT INTO insights
            (post_id, insight_type, domain, summary, competitors, embedding, embedding_model)
        VALUES (?, 'complaint', ?, ?, ?, ?, ?)
        """,
        [
            post_id,
            domain,
            f"summary {post_id}",
            competitors or [],
            embedding,
            MODEL if embedding is not None else None,
        ],
    )


def _edges(conn, edge_type: str) -> list[tuple]:
    return conn.execute(
        """
        SELECT src_type, src_id, dst_type, dst_id, weight, observed_at
        FROM edges WHERE edge_type = ? ORDER BY src_id, dst_id
        """,
        [edge_type],
    ).fetchall()


def test_競合言及をアカウントから製品へのエッジにする(conn):
    _insert_post(conn, post_id="p1", author_id="did:a")
    _insert_post(conn, post_id="p2", author_id="did:a")
    _insert_insight(conn, post_id="p1", competitors=["Roboflow"])
    _insert_insight(conn, post_id="p2", competitors=["Roboflow", "Edge Impulse"])

    rebuild(conn)

    assert _edges(conn, "mentions") == [
        ("author", "did:a", "product", "Edge Impulse", 1.0, datetime(2026, 8, 1)),
        ("author", "did:a", "product", "Roboflow", 2.0, datetime(2026, 8, 1)),
    ]


def test_同じ投稿にヒットしたキーワードを共起エッジにする(conn):
    _insert_post(conn, post_id="p1", keywords=["ラズパイ YOLO", "Jetson 推論"])
    _insert_post(conn, post_id="p2", keywords=["ラズパイ YOLO", "Jetson 推論"])
    _insert_post(conn, post_id="p3", keywords=["ラズパイ YOLO"])

    rebuild(conn)

    assert _edges(conn, "cooccurs") == [
        ("keyword", "Jetson 推論", "keyword", "ラズパイ YOLO", 2.0, datetime(2026, 8, 1))
    ]


def test_共起は片方向だけを持つ(conn):
    """両方向を持つと共起の上位ペアを数えるときに同じ関係を二重に数える。"""
    _insert_post(conn, post_id="p1", keywords=["a", "b"])

    rebuild(conn)

    rows = _edges(conn, "cooccurs")
    assert len(rows) == 1
    assert (rows[0][1], rows[0][3]) == ("a", "b")


def test_キーワードをドメインへのエッジにする(conn):
    _insert_post(conn, post_id="p1", keywords=["ラズパイ YOLO"])
    _insert_post(conn, post_id="p2", keywords=["ラズパイ YOLO"])
    _insert_post(conn, post_id="p3", keywords=["ラズパイ YOLO"])
    _insert_insight(conn, post_id="p1", domain="edge_ai")
    _insert_insight(conn, post_id="p2", domain="edge_ai")
    _insert_insight(conn, post_id="p3", domain="fabrication")

    rebuild(conn)

    assert _edges(conn, "belongs_to") == [
        ("keyword", "ラズパイ YOLO", "domain", "edge_ai", 2.0, datetime(2026, 8, 1)),
        ("keyword", "ラズパイ YOLO", "domain", "fabrication", 1.0, datetime(2026, 8, 1)),
    ]


def test_閾値以上の類似ペアだけをエッジにする(conn):
    _insert_post(conn, post_id="near1")
    _insert_post(conn, post_id="near2")
    _insert_post(conn, post_id="far")
    _insert_insight(conn, post_id="near1", embedding=[1.0, 0.0, 0.0])
    _insert_insight(conn, post_id="near2", embedding=[0.99, 0.1, 0.0])
    _insert_insight(conn, post_id="far", embedding=[0.0, 0.0, 1.0])

    rebuild(conn, similarity_threshold=0.85)

    rows = _edges(conn, "similar_to")
    assert [(r[1], r[3]) for r in rows] == [("near1", "near2")]
    assert rows[0][4] == pytest.approx(0.995, abs=1e-2)


def test_類似エッジは投稿ごとに上位K件で打ち切る(conn):
    """閾値だけで絞ると、話題が集中した期間に完全グラフができて二乗で膨らむ。"""
    for i in range(4):
        _insert_post(conn, post_id=f"p{i}")
        _insert_insight(conn, post_id=f"p{i}", embedding=[1.0, i * 0.01, 0.0])

    rebuild(conn, similarity_threshold=0.5, top_k=1)

    rows = _edges(conn, "similar_to")
    # 4件が全て相互に閾値以上。top_k=1 なら各投稿が1本ずつ張り、
    # 双方向の重複を畳んだ結果は4本未満に収まる
    assert 0 < len(rows) < 6


def test_埋め込みが無ければ類似エッジを作らない(conn):
    _insert_post(conn, post_id="p1")
    _insert_insight(conn, post_id="p1")

    result = rebuild(conn)

    assert result.counts["similar_to"] == 0


def test_再構築しても結果が変わらない(conn):
    _insert_post(conn, post_id="p1", author_id="did:a", keywords=["a", "b"])
    _insert_post(conn, post_id="p2", author_id="did:a", keywords=["a", "b"])
    _insert_insight(conn, post_id="p1", competitors=["X"], embedding=[1.0, 0.0])
    _insert_insight(conn, post_id="p2", competitors=["X"], embedding=[1.0, 0.01])

    first = rebuild(conn)
    snapshot = conn.execute("SELECT * FROM edges ORDER BY ALL").fetchall()

    second = rebuild(conn)

    assert first.counts == second.counts
    assert conn.execute("SELECT * FROM edges ORDER BY ALL").fetchall() == snapshot


def test_導出元から消えた関係は残さない(conn):
    """INSERT OR REPLACE だけでは古いエッジが残り、再構築のたびに単調増加する。"""
    _insert_post(conn, post_id="p1", keywords=["a", "b"])
    rebuild(conn)
    assert len(_edges(conn, "cooccurs")) == 1

    conn.execute("UPDATE posts SET matched_keywords = ['a'] WHERE id = 'p1'")
    rebuild(conn)

    assert _edges(conn, "cooccurs") == []


def test_指定した種別だけを再構築する(conn):
    _insert_post(conn, post_id="p1", author_id="did:a", keywords=["a", "b"])
    _insert_insight(conn, post_id="p1", competitors=["X"])

    result = rebuild(conn, edge_types=("cooccurs",))

    assert result.counts == {"cooccurs": 1}
    assert _edges(conn, "mentions") == []


def test_未知の種別は実行前に拒否する(conn):
    with pytest.raises(ValueError, match="未知の edge_type"):
        rebuild(conn, edge_types=("cooccurs", "unknown"))


def test_埋め込みモデルが混在していたら一行のエラーにする(conn):
    """次元の違うベクトルを list_cosine_similarity へ渡すと素のトレースバックになる。"""
    _insert_post(conn, post_id="p1")
    _insert_post(conn, post_id="p2")
    _insert_insight(conn, post_id="p1", embedding=[1.0, 0.0])
    _insert_insight(conn, post_id="p2", embedding=[1.0, 0.0, 0.0])
    conn.execute("UPDATE insights SET embedding_model = 'model-b' WHERE post_id = 'p2'")

    with pytest.raises(ValueError, match="model-b"):
        rebuild(conn)


def test_モデルが揃っていれば類似エッジを作る(conn):
    """誤検知しないこと。"""
    _insert_post(conn, post_id="p1")
    _insert_post(conn, post_id="p2")
    _insert_insight(conn, post_id="p1", embedding=[1.0, 0.0])
    _insert_insight(conn, post_id="p2", embedding=[1.0, 0.01])

    result = rebuild(conn, similarity_threshold=0.5)

    assert result.counts["similar_to"] == 1


def test_件数が上限を超えたら類似エッジを走らせずに止める(conn, monkeypatch):
    """二乗に比例するため、黙って走らせるとcronが数時間DBを占有する。"""
    monkeypatch.setattr(graph, "_SIMILAR_MAX_INSIGHTS", 1)
    _insert_post(conn, post_id="p1")
    _insert_post(conn, post_id="p2")
    _insert_insight(conn, post_id="p1", embedding=[1.0, 0.0])
    _insert_insight(conn, post_id="p2", embedding=[1.0, 0.01])

    with pytest.raises(ValueError, match="similar_to"):
        rebuild(conn)


def test_上限を超えていてもsimilar_toを外せば再構築できる(conn, monkeypatch):
    """止めるだけで逃げ道が無いと、グラフ全体が使えなくなる。"""
    monkeypatch.setattr(graph, "_SIMILAR_MAX_INSIGHTS", 1)
    _insert_post(conn, post_id="p1", keywords=["a", "b"])
    _insert_insight(conn, post_id="p1", embedding=[1.0, 0.0])
    _insert_post(conn, post_id="p2", keywords=["a", "b"])
    _insert_insight(conn, post_id="p2", embedding=[1.0, 0.01])

    result = rebuild(conn, edge_types=("mentions", "cooccurs", "belongs_to"))

    assert result.counts["cooccurs"] == 1


def test_上限以内なら止めない(conn, monkeypatch):
    """誤検知しないこと。"""
    monkeypatch.setattr(graph, "_SIMILAR_MAX_INSIGHTS", 2)
    _insert_post(conn, post_id="p1")
    _insert_post(conn, post_id="p2")
    _insert_insight(conn, post_id="p1", embedding=[1.0, 0.0])
    _insert_insight(conn, post_id="p2", embedding=[1.0, 0.01])

    result = rebuild(conn, similarity_threshold=0.5)

    assert result.counts["similar_to"] == 1


def test_エッジが無い状態でも落ちない(conn):
    result = rebuild(conn)

    assert result.total == 0
    assert set(result.counts) == {"mentions", "cooccurs", "belongs_to", "similar_to"}
