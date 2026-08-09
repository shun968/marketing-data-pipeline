from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from sns_collector.db import connect
from sns_collector.report import build_report, generate, parse_since, render_markdown

SINCE = datetime(2026, 8, 1)
UNTIL = datetime(2026, 8, 8)


@pytest.fixture
def conn(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as c:
        yield c


def _insert_post(
    conn,
    *,
    post_id,
    platform="bluesky",
    url=None,
    keywords=None,
    posted_at=datetime(2026, 8, 3),
    collected_at=datetime(2026, 8, 3),
) -> None:
    conn.execute(
        """
        INSERT INTO posts
            (id, platform, native_id, url, text, posted_at, collected_at,
             matched_keywords, extraction_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'done')
        """,
        [
            post_id,
            platform,
            post_id,
            url or f"https://example.com/{post_id}",
            f"text {post_id}",
            posted_at,
            collected_at,
            keywords or [],
        ],
    )


def _insert_insight(
    conn,
    *,
    post_id,
    insight_type="complaint",
    domain="edge_ai",
    pain_level=1,
    monetizable=False,
    competitors=None,
    extracted_at=datetime(2026, 8, 3),
) -> None:
    conn.execute(
        """
        INSERT INTO insights
            (post_id, insight_type, domain, summary, pain_level, monetizable,
             competitors, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            post_id,
            insight_type,
            domain,
            f"summary {post_id}",
            pain_level,
            monetizable,
            competitors or [],
            extracted_at,
        ],
    )


class TestParseSince:
    def test_日数指定を期間の開始時刻に変換する(self):
        result = parse_since("7d", now=datetime(2026, 8, 8))
        assert result == datetime(2026, 8, 1)

    def test_不正な形式を拒否する(self):
        with pytest.raises(ValueError, match="7d"):
            parse_since("1week")


class TestDailyCounts:
    def test_期間内をプラットフォーム別日次で数える(self, conn):
        _insert_post(conn, post_id="p1", platform="bluesky", collected_at=datetime(2026, 8, 3))
        _insert_post(conn, post_id="p2", platform="bluesky", collected_at=datetime(2026, 8, 3))
        _insert_post(conn, post_id="p3", platform="hackernews", collected_at=datetime(2026, 8, 4))
        _insert_post(conn, post_id="outside", collected_at=datetime(2026, 7, 20))

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert [(d.day, d.platform, d.count) for d in report.daily_counts] == [
            (date(2026, 8, 3), "bluesky", 2),
            (date(2026, 8, 4), "hackernews", 1),
        ]

    def test_期間の終端は含まない(self, conn):
        _insert_post(conn, post_id="p1", collected_at=UNTIL)

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert report.daily_counts == []


class TestInsightTypeCounts:
    def test_件数と代表投稿を返す(self, conn):
        _insert_post(
            conn, post_id="p1", url="https://example.com/old", posted_at=datetime(2026, 8, 2)
        )
        _insert_post(
            conn, post_id="p2", url="https://example.com/new", posted_at=datetime(2026, 8, 5)
        )
        _insert_insight(
            conn, post_id="p1", insight_type="complaint", extracted_at=datetime(2026, 8, 3)
        )
        _insert_insight(
            conn, post_id="p2", insight_type="complaint", extracted_at=datetime(2026, 8, 3)
        )

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert len(report.insight_type_counts) == 1
        row = report.insight_type_counts[0]
        assert row.insight_type == "complaint"
        assert row.count == 2
        assert row.example_url == "https://example.com/new"

    def test_期間外の抽出は数えない(self, conn):
        _insert_post(conn, post_id="p1")
        _insert_insight(conn, post_id="p1", extracted_at=datetime(2026, 7, 1))

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert report.insight_type_counts == []


class TestDomainCounts:
    def test_前期間との差分を持つ(self, conn):
        period_length = UNTIL - SINCE
        prev_time = SINCE - period_length + (period_length / 2)
        _insert_post(conn, post_id="prev1")
        _insert_insight(conn, post_id="prev1", domain="edge_ai", extracted_at=prev_time)

        _insert_post(conn, post_id="cur1")
        _insert_post(conn, post_id="cur2")
        _insert_insight(conn, post_id="cur1", domain="edge_ai", extracted_at=datetime(2026, 8, 3))
        _insert_insight(conn, post_id="cur2", domain="edge_ai", extracted_at=datetime(2026, 8, 4))

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert len(report.domain_counts) == 1
        row = report.domain_counts[0]
        assert row.domain == "edge_ai"
        assert row.count == 2
        assert row.previous_count == 1

    def test_前期間に無いドメインは0として扱う(self, conn):
        _insert_post(conn, post_id="p1")
        _insert_insight(conn, post_id="p1", domain="fabrication", extracted_at=datetime(2026, 8, 3))

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert report.domain_counts[0].previous_count == 0


class TestTopSignals:
    def test_pain3かつmonetizableのみ全件返す(self, conn):
        _insert_post(conn, post_id="p1", posted_at=datetime(2026, 8, 2))
        _insert_post(conn, post_id="p2", posted_at=datetime(2026, 8, 5))
        _insert_post(conn, post_id="p3", posted_at=datetime(2026, 8, 4))
        _insert_insight(
            conn, post_id="p1", pain_level=3, monetizable=True, extracted_at=datetime(2026, 8, 3)
        )
        _insert_insight(
            conn, post_id="p2", pain_level=3, monetizable=True, extracted_at=datetime(2026, 8, 3)
        )
        _insert_insight(
            conn, post_id="p3", pain_level=2, monetizable=True, extracted_at=datetime(2026, 8, 3)
        )

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert [s.post_id for s in report.top_signals] == ["p2", "p1"]

    def test_該当が無ければ空リスト(self, conn):
        _insert_post(conn, post_id="p1")
        _insert_insight(conn, post_id="p1", pain_level=1, monetizable=False)

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert report.top_signals == []


class TestTopKeywords:
    def test_頻度順に並べtop_nで打ち切る(self, conn):
        _insert_post(conn, post_id="p1", keywords=["a", "b"])
        _insert_post(conn, post_id="p2", keywords=["a"])
        _insert_post(conn, post_id="p3", keywords=["c"])

        report = build_report(conn, since=SINCE, until=UNTIL, top_n=2)

        assert [(k.keyword, k.count) for k in report.top_keywords] == [("a", 2), ("b", 1)]


class TestTopKeywordPairs:
    def test_同一投稿内のペアを片方向で数える(self, conn):
        _insert_post(conn, post_id="p1", keywords=["a", "b"])
        _insert_post(conn, post_id="p2", keywords=["a", "b"])

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert [(p.keyword_a, p.keyword_b, p.count) for p in report.top_keyword_pairs] == [
            ("a", "b", 2)
        ]


class TestNewCompetitors:
    def test_初出がこの期間のものだけを返す(self, conn):
        _insert_post(conn, post_id="old1")
        _insert_insight(
            conn, post_id="old1", competitors=["Roboflow"], extracted_at=datetime(2026, 7, 1)
        )
        _insert_post(conn, post_id="old2")
        _insert_insight(
            conn, post_id="old2", competitors=["Roboflow"], extracted_at=datetime(2026, 8, 3)
        )

        _insert_post(conn, post_id="new1")
        _insert_insight(
            conn, post_id="new1", competitors=["Edge Impulse"], extracted_at=datetime(2026, 8, 4)
        )

        report = build_report(conn, since=SINCE, until=UNTIL)

        assert [c.product for c in report.new_competitors] == ["Edge Impulse"]


class TestRenderMarkdown:
    def test_空のレポートでも落ちない(self, conn):
        report = build_report(conn, since=SINCE, until=UNTIL)

        markdown = render_markdown(report)

        assert "定期レポート" in markdown
        assert "該当なし" in markdown

    def test_主要セクションの見出しを含む(self, conn):
        report = build_report(conn, since=SINCE, until=UNTIL)

        markdown = render_markdown(report)

        for heading in [
            "新規観測件数",
            "insight_type別の分布",
            "domain別の件数",
            "最重要シグナル",
            "頻出キーワード",
            "キーワード共起",
            "新規に観測された競合製品",
        ]:
            assert heading in markdown


class TestGenerate:
    def test_ファイルを書き出す(self, conn, tmp_path):
        _insert_post(conn, post_id="p1", collected_at=datetime(2026, 8, 3))

        result = generate(conn, tmp_path / "reports", since="7d", now=UNTIL)

        assert result.path.exists()
        assert result.path.read_text(encoding="utf-8") == result.markdown
        assert result.path.name == "report-2026-08-01_2026-08-08.md"

    def test_同じ期間の再実行は同じファイルへ上書きする(self, conn, tmp_path):
        reports_dir = tmp_path / "reports"
        first = generate(conn, reports_dir, since="7d", now=UNTIL)

        _insert_post(conn, post_id="p1", collected_at=datetime(2026, 8, 3))
        second = generate(conn, reports_dir, since="7d", now=UNTIL)

        assert first.path == second.path
        assert len(list(reports_dir.glob("*.md"))) == 1
