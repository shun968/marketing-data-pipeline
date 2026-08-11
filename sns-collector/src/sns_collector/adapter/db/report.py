"""定期レポート（F-14〜F-16）。

`posts` / `insights` に対する**決定論的な集計のみ**を行い、Markdownを書き出す。
LLMを呼ばないためcronで無人実行できる（design.md §4.6）。

洞察・仮説の加筆（F-16）はこの定量サマリを入力として別途Claude Codeセッションで行う。
作業指示は `prompts/report-insights.md` にあり、ここでは生成しない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

DEFAULT_SINCE = "7d"
DEFAULT_TOP_N = 10

_SINCE_RE = re.compile(r"^(\d+)d$")


def _to_naive_utc(value: datetime) -> datetime:
    """aware datetimeをUTCのnaiveへ揃える。既にnaiveならそのまま返す。

    `posts.posted_at` 等と同じくnaive UTCで統一しないと比較・減算が壊れる
    （db/adapters.py の `_parse_timestamp` と同じ理由）。
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    """`7d` のような相対指定を、期間の開始時刻（naive UTC）へ変換する。

    他コマンドの `--since` はISO日付だが、レポートは「直近N日」の反復実行が
    主用途のため、日付を毎回書き換えずに済む相対形式にしている（design.md §4.1）。
    """
    m = _SINCE_RE.match(value)
    if not m:
        raise ValueError(f"--since は '7d' のような形式で指定する: {value}")
    days = int(m.group(1))
    now = _to_naive_utc(now or datetime.now(UTC))
    return now - timedelta(days=days)


@dataclass(frozen=True)
class DailyCount:
    day: date
    platform: str
    count: int


@dataclass(frozen=True)
class TypeCount:
    insight_type: str
    count: int
    example_url: str | None


@dataclass(frozen=True)
class DomainCount:
    domain: str
    count: int
    previous_count: int
    example_url: str | None


@dataclass(frozen=True)
class TopSignal:
    post_id: str
    platform: str
    url: str | None
    summary: str | None
    domain: str | None


@dataclass(frozen=True)
class KeywordCount:
    keyword: str
    count: int


@dataclass(frozen=True)
class KeywordPair:
    keyword_a: str
    keyword_b: str
    count: int


@dataclass(frozen=True)
class NewCompetitor:
    product: str
    first_seen: datetime
    example_url: str | None


@dataclass(frozen=True)
class Report:
    since: datetime
    until: datetime
    daily_counts: list[DailyCount] = field(default_factory=list)
    insight_type_counts: list[TypeCount] = field(default_factory=list)
    domain_counts: list[DomainCount] = field(default_factory=list)
    top_signals: list[TopSignal] = field(default_factory=list)
    top_keywords: list[KeywordCount] = field(default_factory=list)
    top_keyword_pairs: list[KeywordPair] = field(default_factory=list)
    new_competitors: list[NewCompetitor] = field(default_factory=list)


def _daily_counts(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime
) -> list[DailyCount]:
    rows = conn.execute(
        """
        SELECT platform, date_trunc('day', collected_at)::DATE AS day, count(*)
        FROM posts
        WHERE collected_at >= ? AND collected_at < ?
        GROUP BY 1, 2
        ORDER BY 2, 1
        """,
        [since, until],
    ).fetchall()
    return [DailyCount(day=r[1], platform=r[0], count=r[2]) for r in rows]


def _insight_type_counts(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime
) -> list[TypeCount]:
    rows = conn.execute(
        """
        SELECT i.insight_type, count(*), arg_max(p.url, p.posted_at)
        FROM insights i JOIN posts p ON p.id = i.post_id
        WHERE i.extracted_at >= ? AND i.extracted_at < ?
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        [since, until],
    ).fetchall()
    return [TypeCount(insight_type=r[0], count=r[1], example_url=r[2]) for r in rows]


def _domain_counts(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime
) -> list[DomainCount]:
    """当期の件数に加え、直前の同じ長さの期間との比較を持つ。

    直前期間に存在しなかったドメインは previous_count=0 として扱う。0で
    割ると増減率が定義できないため、比率ではなく差分で見せる。

    **2回に分けたクエリを`FILTER`句で1本化しない。** `report`は週次cronの
    低頻度実行でありホットパスではないため、2回の軽いCOUNTクエリを1回へ
    減らす利益より、バインドパラメータの並びを10個手で管理する複雑さが
    もたらすバグ混入のリスクのほうが大きいと判断した。
    """
    period_length = until - since
    prev_since = since - period_length

    current = conn.execute(
        """
        SELECT i.domain, count(*), arg_max(p.url, p.posted_at)
        FROM insights i JOIN posts p ON p.id = i.post_id
        WHERE i.extracted_at >= ? AND i.extracted_at < ? AND i.domain IS NOT NULL
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        [since, until],
    ).fetchall()
    previous = dict(
        conn.execute(
            """
            SELECT i.domain, count(*)
            FROM insights i JOIN posts p ON p.id = i.post_id
            WHERE i.extracted_at >= ? AND i.extracted_at < ? AND i.domain IS NOT NULL
            GROUP BY 1
            """,
            [prev_since, since],
        ).fetchall()
    )
    return [
        DomainCount(domain=r[0], count=r[1], previous_count=previous.get(r[0], 0), example_url=r[2])
        for r in current
    ]


def _top_signals(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime
) -> list[TopSignal]:
    """`pain_level=3` かつ `monetizable=true` の投稿。最重要シグナルのため全件を返す(上限なし)。"""
    rows = conn.execute(
        """
        SELECT i.post_id, p.platform, p.url, i.summary, i.domain
        FROM insights i JOIN posts p ON p.id = i.post_id
        WHERE i.extracted_at >= ? AND i.extracted_at < ?
          AND i.pain_level = 3 AND i.monetizable = true
        ORDER BY p.posted_at DESC
        """,
        [since, until],
    ).fetchall()
    return [
        TopSignal(post_id=r[0], platform=r[1], url=r[2], summary=r[3], domain=r[4]) for r in rows
    ]


def _top_keywords(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime, top_n: int
) -> list[KeywordCount]:
    rows = conn.execute(
        """
        WITH kw AS (
            SELECT unnest(matched_keywords) AS keyword
            FROM posts
            WHERE collected_at >= ? AND collected_at < ?
        )
        SELECT keyword, count(*) FROM kw GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?
        """,
        [since, until, top_n],
    ).fetchall()
    return [KeywordCount(keyword=r[0], count=r[1]) for r in rows]


def _top_keyword_pairs(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime, top_n: int
) -> list[KeywordPair]:
    # graph.py の cooccurs と同じ形（片方向のみ・同一投稿内でのペア）だが、
    # `edges` は全期間の累積であり期間を切れないため、ここでは直接集計する。
    rows = conn.execute(
        """
        WITH kw AS (
            SELECT DISTINCT id, unnest(matched_keywords) AS keyword
            FROM posts
            WHERE collected_at >= ? AND collected_at < ?
        )
        SELECT a.keyword, b.keyword, count(*)
        FROM kw a JOIN kw b ON a.id = b.id AND a.keyword < b.keyword
        GROUP BY 1, 2
        ORDER BY 3 DESC, 1, 2
        LIMIT ?
        """,
        [since, until, top_n],
    ).fetchall()
    return [KeywordPair(keyword_a=r[0], keyword_b=r[1], count=r[2]) for r in rows]


def _new_competitors(
    conn: duckdb.DuckDBPyConnection, since: datetime, until: datetime
) -> list[NewCompetitor]:
    """初めて言及された競合製品。過去のどの期間にも登場していないものだけを拾う。

    「新規」の判定は全期間の `extracted_at` 最小値がこの期間に収まるかで行う。
    期間内だけを見て集計すると、以前から言及され続けている製品を毎回
    「新規」と報告してしまう。
    """
    rows = conn.execute(
        """
        WITH mention AS (
            SELECT
                trim(unnest(i.competitors)) AS product,
                i.extracted_at AS extracted_at,
                p.url AS url,
                p.posted_at AS posted_at
            FROM insights i JOIN posts p ON p.id = i.post_id
            WHERE i.competitors IS NOT NULL
        ),
        cleaned AS (
            SELECT * FROM mention WHERE product IS NOT NULL AND length(product) > 0
        ),
        first_seen AS (
            SELECT product, min(extracted_at) AS first_extracted_at
            FROM cleaned
            GROUP BY 1
        )
        SELECT f.product, f.first_extracted_at, arg_max(c.url, c.posted_at)
        FROM first_seen f JOIN cleaned c ON c.product = f.product
        WHERE f.first_extracted_at >= ? AND f.first_extracted_at < ?
        GROUP BY 1, 2
        ORDER BY 2 DESC, 1
        """,
        [since, until],
    ).fetchall()
    return [NewCompetitor(product=r[0], first_seen=r[1], example_url=r[2]) for r in rows]


def build_report(
    conn: duckdb.DuckDBPyConnection,
    *,
    since: datetime,
    until: datetime | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> Report:
    until = _to_naive_utc(until or datetime.now(UTC))
    return Report(
        since=since,
        until=until,
        daily_counts=_daily_counts(conn, since, until),
        insight_type_counts=_insight_type_counts(conn, since, until),
        domain_counts=_domain_counts(conn, since, until),
        top_signals=_top_signals(conn, since, until),
        top_keywords=_top_keywords(conn, since, until, top_n),
        top_keyword_pairs=_top_keyword_pairs(conn, since, until, top_n),
        new_competitors=_new_competitors(conn, since, until),
    )


def _fmt_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def _escape_md(value: str | None) -> str:
    """Markdownのテーブル・箇条書きへ埋め込んでも壊れない形にする。

    `summary`・`competitors`はLLM抽出の自由記述で統制語彙が無い
    （extract/schema.py は非空・400字以内しか検証しない）。`|`が入ると
    テーブルの列がずれ、改行が入ると行・箇条書き項目が壊れる。
    """
    if not value:
        return "-"
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"# 定期レポート {_fmt_dt(report.since)} 〜 {_fmt_dt(report.until)}")
    lines.append("")
    lines.append(
        "この節までは決定論的な集計のみ。洞察・仮説の加筆は "
        "`prompts/report-insights.md` の作業指示に従い別セッションで行う。"
    )
    lines.append("")

    lines.append("## 新規観測件数（プラットフォーム別・日次）")
    lines.append("")
    if report.daily_counts:
        lines.append("| 日付 | platform | 件数 |")
        lines.append("|---|---|---|")
        for row in report.daily_counts:
            lines.append(f"| {row.day} | {_escape_md(row.platform)} | {row.count} |")
    else:
        lines.append("該当なし")
    lines.append("")

    lines.append("## insight_type別の分布")
    lines.append("")
    if report.insight_type_counts:
        lines.append("| insight_type | 件数 | 代表投稿 |")
        lines.append("|---|---|---|")
        for row in report.insight_type_counts:
            lines.append(
                f"| {_escape_md(row.insight_type)} | {row.count} | {_escape_md(row.example_url)} |"
            )
    else:
        lines.append("該当なし")
    lines.append("")

    lines.append("## domain別の件数（前期間比）")
    lines.append("")
    if report.domain_counts:
        lines.append("| domain | 件数 | 前期間 | 差分 | 代表投稿 |")
        lines.append("|---|---|---|---|---|")
        for row in report.domain_counts:
            diff = row.count - row.previous_count
            sign = "+" if diff >= 0 else ""
            lines.append(
                f"| {_escape_md(row.domain)} | {row.count} | {row.previous_count} | "
                f"{sign}{diff} | {_escape_md(row.example_url)} |"
            )
    else:
        lines.append("該当なし")
    lines.append("")

    lines.append("## 最重要シグナル（pain_level=3 かつ monetizable=true の全件）")
    lines.append("")
    if report.top_signals:
        for row in report.top_signals:
            summary = _escape_md(row.summary) if row.summary else row.post_id
            lines.append(f"- [{_escape_md(row.platform)}/{_escape_md(row.domain)}] {summary}")
            if row.url:
                lines.append(f"  {row.url}")
    else:
        lines.append("該当なし")
    lines.append("")

    lines.append("## 頻出キーワード")
    lines.append("")
    if report.top_keywords:
        lines.append("| キーワード | 件数 |")
        lines.append("|---|---|")
        for row in report.top_keywords:
            lines.append(f"| {_escape_md(row.keyword)} | {row.count} |")
    else:
        lines.append("該当なし")
    lines.append("")

    lines.append("## キーワード共起 上位")
    lines.append("")
    if report.top_keyword_pairs:
        lines.append("| キーワードA | キーワードB | 件数 |")
        lines.append("|---|---|---|")
        for row in report.top_keyword_pairs:
            lines.append(
                f"| {_escape_md(row.keyword_a)} | {_escape_md(row.keyword_b)} | {row.count} |"
            )
    else:
        lines.append("該当なし")
    lines.append("")

    lines.append("## 新規に観測された競合製品")
    lines.append("")
    if report.new_competitors:
        lines.append("| 製品 | 初出 | 代表投稿 |")
        lines.append("|---|---|---|")
        for row in report.new_competitors:
            lines.append(
                f"| {_escape_md(row.product)} | {_fmt_dt(row.first_seen)} | "
                f"{_escape_md(row.example_url)} |"
            )
    else:
        lines.append("該当なし")
    lines.append("")

    return "\n".join(lines)


@dataclass(frozen=True)
class GenerateResult:
    report: Report
    path: Path
    markdown: str


def generate(
    conn: duckdb.DuckDBPyConnection,
    reports_dir: Path,
    *,
    since: str = DEFAULT_SINCE,
    now: datetime | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> GenerateResult:
    """集計してMarkdownを書き出す。同じ `since` と同じ日に実行すれば同じパスへ上書きする。

    ファイル名を秒まで持たせると、cronで日次実行するたびにファイルが増え続け、
    `reports/` が肥大化する。日付だけにすることで、同日の再実行は上書きになる。
    """
    until = _to_naive_utc(now or datetime.now(UTC))
    start = parse_since(since, now=until)

    report = build_report(conn, since=start, until=until, top_n=top_n)
    markdown = render_markdown(report)

    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"report-{_fmt_dt(start)}_{_fmt_dt(until)}.md"
    path.write_text(markdown, encoding="utf-8")

    return GenerateResult(report=report, path=path, markdown=markdown)
