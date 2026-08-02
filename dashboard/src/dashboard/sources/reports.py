"""レポートと収集ログの読み取り。

対象は2種類。

- 生成レポート  sns-collector/reports/*.md（日次・週次の定量サマリと分析結果）
- 収集ログ      sns-collector/state/.logs/*.log（実行結果）

どちらも収集データそのものであり、gitignore配下にある。
**この画面は読むだけで、リポジトリへ書き戻さない。**

レポートはまだ生成されていない(roadmap Phase 5)。ディレクトリが無い場合も
空として扱い、生成され次第そのまま出るようにしてある。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dashboard import markup
from dashboard.paths import relative_to_repo, resolve_within, roots

# 1回の表示で読むログの行数。収集ログは追記され続けるため上限を置く
LOG_TAIL_LINES = 400


@dataclass(frozen=True)
class Report:
    slug: str
    title: str
    path: str
    modified: str
    size: int


@dataclass(frozen=True)
class RunEntry:
    """収集ログ1行の解釈結果。"""

    raw: str
    started_at: str | None
    keyword: str | None
    fetched: int | None
    added: int | None
    skipped: int | None


@dataclass(frozen=True)
class CollectorLog:
    platform: str
    path: str
    modified: str
    entries: list[RunEntry]
    truncated: bool

    @property
    def total_added(self) -> int:
        return sum(e.added for e in self.entries if e.added is not None)

    @property
    def total_fetched(self) -> int:
        return sum(e.fetched for e in self.entries if e.fetched is not None)

    @property
    def last_run(self) -> str | None:
        for entry in reversed(self.entries):
            if entry.started_at:
                return entry.started_at
        return None


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def list_reports() -> list[Report]:
    directory = roots().reports
    if not directory.is_dir():
        return []

    items: list[Report] = []
    for path in sorted(directory.rglob("*.md"), reverse=True):
        relative = path.relative_to(directory)
        items.append(
            Report(
                slug=str(relative),
                title=path.stem,
                path=relative_to_repo(path),
                modified=_mtime(path),
                size=path.stat().st_size,
            )
        )
    return items


def read_report(slug: str) -> tuple[Report, str] | None:
    """レポート本文をHTMLで返す。

    slug はURLから来る。**必ず許可ルート配下へ解決する**
    (resolve_within が外を指すパスを弾く)。
    """
    directory = roots().reports
    path = resolve_within(directory, slug)
    if not path.is_file() or path.suffix != ".md":
        return None

    report = Report(
        slug=slug,
        title=path.stem,
        path=relative_to_repo(path),
        modified=_mtime(path),
        size=path.stat().st_size,
    )
    return report, markup.render(path.read_text(encoding="utf-8"))


_START = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*start:\s*(?P<platform>\S+)")
_RESULT = re.compile(
    r"^\[(?P<platform>[^:\]]+):(?P<keyword>[^\]]+)\]\s*"
    r"取得:\s*(?P<fetched>\d+)件\s*/\s*新規:\s*(?P<added>\d+)件\s*/\s*スキップ:\s*(?P<skipped>\d+)件"
)


def _parse_log_line(line: str, current_start: str | None) -> tuple[RunEntry, str | None]:
    start = _START.match(line)
    if start:
        ts = start.group("ts")
        return RunEntry(line, ts, None, None, None, None), ts

    result = _RESULT.match(line)
    if result:
        return (
            RunEntry(
                raw=line,
                started_at=current_start,
                keyword=result.group("keyword"),
                fetched=int(result.group("fetched")),
                added=int(result.group("added")),
                skipped=int(result.group("skipped")),
            ),
            current_start,
        )

    return RunEntry(line, current_start, None, None, None, None), current_start


def list_collector_logs() -> list[CollectorLog]:
    directory = roots().collector_logs
    if not directory.is_dir():
        return []

    logs: list[CollectorLog] = []
    for path in sorted(directory.glob("*.log")):
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        truncated = len(all_lines) > LOG_TAIL_LINES
        lines = all_lines[-LOG_TAIL_LINES:]

        entries: list[RunEntry] = []
        current_start: str | None = None
        for line in lines:
            if not line.strip():
                continue
            entry, current_start = _parse_log_line(line, current_start)
            entries.append(entry)

        logs.append(
            CollectorLog(
                platform=path.stem,
                path=relative_to_repo(path),
                modified=_mtime(path),
                entries=entries,
                truncated=truncated,
            )
        )
    return logs


def keyword_summary(logs: list[CollectorLog]) -> list[dict[str, object]]:
    """キーワード別の収集実績。

    キーワード設計の見直し(README の2原則)に使う。新規0件が続く語は
    改訂候補であり、これは事業方針側の判断材料になる。
    """
    totals: dict[tuple[str, str], dict[str, int]] = {}
    for log in logs:
        for entry in log.entries:
            if entry.keyword is None:
                continue
            key = (log.platform, entry.keyword)
            bucket = totals.setdefault(key, {"fetched": 0, "added": 0, "runs": 0})
            bucket["fetched"] += entry.fetched or 0
            bucket["added"] += entry.added or 0
            bucket["runs"] += 1

    rows = [
        {
            "platform": platform,
            "keyword": keyword,
            "fetched": values["fetched"],
            "added": values["added"],
            "runs": values["runs"],
        }
        for (platform, keyword), values in totals.items()
    ]
    # 新規獲得の少ない順。見直すべき語が上に来る
    rows.sort(key=lambda r: (r["added"], -r["fetched"]))
    return rows
