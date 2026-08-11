"""キーワード集計の判定ロジック。

集計そのものは (matched_keywords, text) の列だけで決まるため、DBは要らない
（SQLは `adapter/db/queries.py` に分離した。ADR-0011）。
クエリとの結線だけ、最後に1件だけDB経由で確認する。
"""

from __future__ import annotations

from pathlib import Path

from sns_collector.adapter.db import connect, insert_records
from sns_collector.adapter.db.queries import keyword_rows
from sns_collector.usecase.keyword_quality import compute_keyword_stats
from tests.conftest import BLUESKY_RECORD


def test_キーワード別に件数と痛み件数を集計する():
    stats = compute_keyword_stats(
        [
            (["kw"], "i tried but doesn't work"),
            (["kw"], "普通の投稿"),
        ]
    )

    assert len(stats) == 1
    assert stats[0].keyword == "kw"
    assert stats[0].count == 2
    assert stats[0].pain_count == 1
    assert stats[0].pain_rate == 0.5


def test_複数キーワードにマッチした投稿はそれぞれへ加算される():
    """既知の投稿が別キーワードでも見つかった場合、matched_keywordsは和集合になる
    （record_keyword_hits）。集計もその和集合ベースで行う。
    """
    stats = compute_keyword_stats([(["a", "b"], "本文")])

    assert {s.keyword: s.count for s in stats} == {"a": 1, "b": 1}


def test_投稿が無いキーワードは母数不足として扱う():
    """0件のキーワードは行に現れない。pain_rate は母数0でNoneになる。"""
    stats = compute_keyword_stats([])
    assert stats == []


def test_keywordが無い投稿は集計に含まれない():
    stats = compute_keyword_stats([([], "キーワード無し"), (None, "None")])
    assert stats == []


def test_多い順に並ぶ():
    stats = compute_keyword_stats(
        [(["少"], "t"), (["多"], "t"), (["多"], "t"), (["中"], "t"), (["中"], "t"), (["多"], "t")]
    )

    assert [s.keyword for s in stats] == ["多", "中", "少"]


def test_痛み表現は大小文字を問わず拾う():
    stats = compute_keyword_stats([(["kw"], "I TRIED everything")])
    assert stats[0].pain_count == 1


def test_本文が空でも落ちない():
    stats = compute_keyword_stats([(["kw"], None), (["kw"], "")])
    assert stats[0].count == 2
    assert stats[0].pain_count == 0


def test_クエリと集計が繋がる(tmp_path: Path):
    """SQLを分離したことで結線がずれても気づけるよう、1件だけ実DBで通す。"""
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
                }
            ],
        )
        stats = compute_keyword_stats(keyword_rows(conn, "bluesky"))

    assert [(s.keyword, s.count, s.pain_count) for s in stats] == [("kw", 1, 1)]
