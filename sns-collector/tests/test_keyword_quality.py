from __future__ import annotations

from pathlib import Path

from sns_collector.db import connect, insert_records
from sns_collector.keyword_quality import KeywordStat, compute_keyword_stats
from tests.conftest import BLUESKY_RECORD


def test_キーワード別に件数と痛み件数を集計する(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(
            conn,
            "bluesky",
            [
                {
                    **BLUESKY_RECORD,
                    "post_id": "p1",
                    "keyword": "kw",
                    "text": "i tried but doesn't work",
                },
                {**BLUESKY_RECORD, "post_id": "p2", "keyword": "kw", "text": "普通の投稿"},
            ],
        )

        stats = compute_keyword_stats(conn, "bluesky")

    assert len(stats) == 1
    assert stats[0].keyword == "kw"
    assert stats[0].count == 2
    assert stats[0].pain_count == 1
    assert stats[0].pain_rate == 0.5


def test_複数キーワードにマッチした投稿はそれぞれへ加算される(tmp_path: Path):
    """既知の投稿が別キーワードでも見つかった場合、matched_keywordsは和集合になる
    （record_keyword_hits）。集計もその和集合ベースで行う。
    """
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [{**BLUESKY_RECORD, "post_id": "p1", "keyword": "a"}])
        insert_records(conn, "bluesky", [{**BLUESKY_RECORD, "post_id": "p1", "keyword": "b"}])

        stats = compute_keyword_stats(conn, "bluesky")

    keywords = {s.keyword for s in stats}
    assert keywords == {"a", "b"}
    assert all(s.count == 1 for s in stats)


def test_投稿が無いキーワードは母数不足として扱う(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        stats = compute_keyword_stats(conn, "bluesky")

    assert stats == []


def test_件数0はpain_rateがNone():
    """0除算を避ける。母数が無ければ判定不能として扱う。"""
    stat = KeywordStat(keyword="kw", count=0, pain_count=0)
    assert stat.pain_rate is None


def test_keywordが無い投稿は集計に含まれない(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [{**BLUESKY_RECORD, "post_id": "p1", "keyword": None}])
        stats = compute_keyword_stats(conn, "bluesky")

    assert stats == []


def test_多い順に並ぶ(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(
            conn,
            "bluesky",
            [
                {**BLUESKY_RECORD, "post_id": "p1", "keyword": "少ない"},
                {**BLUESKY_RECORD, "post_id": "p2", "keyword": "多い"},
                {**BLUESKY_RECORD, "post_id": "p3", "keyword": "多い"},
            ],
        )

        stats = compute_keyword_stats(conn, "bluesky")

    assert [s.keyword for s in stats] == ["多い", "少ない"]
