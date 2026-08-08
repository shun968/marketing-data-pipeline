from __future__ import annotations

from pathlib import Path

import pytest

from sns_collector.db import connect, insert_records
from sns_collector.embed import embed
from tests.conftest import BLUESKY_RECORD


def _fake_embedder(dim: int = 4):
    def _embed(texts):
        return [[float(len(t))] * dim for t in texts]

    return _embed


def _insert_insight(conn, post_id: str, summary: str | None = "テスト用の要約") -> None:
    conn.execute(
        """
        INSERT INTO insights (post_id, insight_type, domain, summary, pain_level, monetizable)
        VALUES (?, 'complaint', 'edge_ai', ?, 1, false)
        """,
        [post_id, summary],
    )


@pytest.fixture
def conn_with_insight(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        post_id = conn.execute("SELECT id FROM posts").fetchone()[0]
        _insert_insight(conn, post_id)
        yield conn, post_id


def test_未埋め込みの行にベクトルを付与する(conn_with_insight):
    conn, post_id = conn_with_insight

    result = embed(conn, limit=10, model_name="fake-model", embedder=_fake_embedder())

    assert result.embedded == 1
    assert result.model == "fake-model"
    assert result.dimension == 4
    row = conn.execute(
        "SELECT embedding, embedding_model FROM insights WHERE post_id = ?", [post_id]
    ).fetchone()
    assert row[0] is not None
    assert row[1] == "fake-model"


def test_再実行しても既存の埋め込みは変わらない(conn_with_insight):
    """embedding IS NULL の行だけが対象のため、再実行は冪等。"""
    conn, post_id = conn_with_insight

    embed(conn, limit=10, model_name="fake-model", embedder=_fake_embedder())
    before = conn.execute("SELECT embedding FROM insights WHERE post_id = ?", [post_id]).fetchone()

    result = embed(conn, limit=10, model_name="other-model", embedder=_fake_embedder(dim=8))

    assert result.embedded == 0
    after = conn.execute("SELECT embedding FROM insights WHERE post_id = ?", [post_id]).fetchone()
    assert before == after


def test_summaryがNULLの行は対象にならない(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        post_id = conn.execute("SELECT id FROM posts").fetchone()[0]
        _insert_insight(conn, post_id, summary=None)

        result = embed(conn, limit=10, model_name="fake-model", embedder=_fake_embedder())

        assert result.embedded == 0


class _FailOnUpdate:
    """insights への UPDATE だけを失敗させる薄いプロキシ(test_extract.pyの手法を流用)。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args, **kwargs):
        if "UPDATE insights" in sql:
            raise RuntimeError("書き込みに失敗した")
        return self._conn.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        if "UPDATE insights" in sql:
            raise RuntimeError("書き込みに失敗した")
        return self._conn.executemany(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_書き込み失敗時はロールバックし部分的な埋め込みを残さない(conn_with_insight):
    conn, post_id = conn_with_insight

    with pytest.raises(RuntimeError, match="書き込みに失敗した"):
        embed(_FailOnUpdate(conn), limit=10, model_name="fake-model", embedder=_fake_embedder())

    row = conn.execute(
        "SELECT embedding, embedding_model FROM insights WHERE post_id = ?", [post_id]
    ).fetchone()
    assert row == (None, None)
