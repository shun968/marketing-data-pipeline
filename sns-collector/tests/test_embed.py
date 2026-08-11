from __future__ import annotations

from pathlib import Path

import pytest

from sns_collector.adapter.db import connect, insert_records
from sns_collector.adapter.db.embedding import embed
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

    # モデル名は揃える。異なるモデルでの再実行は ensure_model_matches が拒否する
    # 組み合わせであり、冪等性とは別の失敗モードとして下でテストしている
    result = embed(conn, limit=10, model_name="fake-model", embedder=_fake_embedder(dim=8))

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


def test_要求モデルがコーパスと違えば埋め込みを拒否する(conn_with_insight):
    """次元の違うモデルを混ぜると search が例外で落ちる。事前に止める。"""
    conn, post_id = conn_with_insight
    embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())

    _insert_insight(conn, "bluesky:another", summary="別の要約")
    with pytest.raises(ValueError, match="model-a"):
        embed(conn, limit=10, model_name="model-b", embedder=_fake_embedder(dim=8))


def test_既に混在しているDBはどのモデルでも拒否し全部を挙げる(conn_with_insight):
    """壊れたDBを診断できる唯一の経路。要求モデルと一致する行が在っても通さない。"""
    conn, post_id = conn_with_insight
    embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())
    _insert_insight(conn, "bluesky:another", summary="別の要約")
    embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())
    conn.execute("UPDATE insights SET embedding_model = 'model-b' WHERE post_id = ?", [post_id])

    with pytest.raises(ValueError) as e:
        embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())
    assert "model-a" in str(e.value)
    assert "model-b" in str(e.value)


def test_モデル名が不明な埋め込みは一致とみなさない(conn_with_insight):
    """embedding_model は migration 2 で後から足した列。

    ベクトルはあるのにモデル名が無い行を「埋め込みが無い」と同じ扱いにすると、
    照合が素通りして次元の違うベクトルが並ぶ。分からないものは通さない。
    """
    conn, post_id = conn_with_insight
    embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())
    conn.execute("UPDATE insights SET embedding_model = NULL")

    _insert_insight(conn, "bluesky:another", summary="別の要約")
    with pytest.raises(ValueError, match="不明"):
        embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder(dim=8))


def test_同じモデルなら追加の埋め込みを通す(conn_with_insight):
    """誤検知しないこと。既存と同じモデルは何度でも足せる。"""
    conn, post_id = conn_with_insight
    embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())

    _insert_insight(conn, "bluesky:another", summary="別の要約")
    result = embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())
    assert result.embedded == 1


def test_埋め込みが1件も無ければどのモデルでも通る(conn_with_insight):
    """誤検知しないこと。初回実行はモデル名を自由に選べる。"""
    conn, post_id = conn_with_insight
    result = embed(conn, limit=10, model_name="model-b", embedder=_fake_embedder())
    assert result.embedded == 1


def test_埋め込み対象が無くてもモデル不一致は拒否する(conn_with_insight):
    """黙って0件成功にしない。--model の指定ミスをその場で知らせる。"""
    conn, post_id = conn_with_insight
    embed(conn, limit=10, model_name="model-a", embedder=_fake_embedder())

    with pytest.raises(ValueError, match="model-a"):
        embed(conn, limit=10, model_name="model-b", embedder=_fake_embedder(dim=8))
