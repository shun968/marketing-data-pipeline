"""ガードレール抵触メトリクスの集計。

入力は scripts/record-check.sh が追記する .metrics/guardrail-events.jsonl。
1行1イベントで、スキーマは記録側の先頭コメントにある。

**この集計の用途はガードレールの見直しである。** 見たいのは次の3点。

1. 一度も発火していないルール → 剥がす候補。ゲートは増やすほど遅くなる
2. 繰り返し発火するルール → 検査で止めるのではなく設計で潰す候補
3. 検査の所要時間 → pre-commit が遅いと --no-verify の常用を招く

壊れた行は落として読み進める。記録は観測であり、
1行の破損で画面全体が見られなくなるほうが損失が大きい。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from dashboard.paths import roots

EVENTS_FILENAME = "guardrail-events.jsonl"


@dataclass(frozen=True)
class Event:
    ts: datetime
    check: str
    context: str
    exit_code: int
    duration_ms: int
    violations: int
    rules: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return self.exit_code != 0


@dataclass(frozen=True)
class CheckStat:
    check: str
    runs: int
    blocks: int
    violations: int
    total_ms: int

    @property
    def block_rate(self) -> float:
        return self.blocks / self.runs if self.runs else 0.0

    @property
    def avg_ms(self) -> int:
        return round(self.total_ms / self.runs) if self.runs else 0


@dataclass(frozen=True)
class RuleStat:
    rule: str
    hits: int
    last_seen: str


def events_path() -> Path:
    return roots().metrics / EVENTS_FILENAME


def _parse(line: str) -> Event | None:
    try:
        raw = json.loads(line)
        return Event(
            ts=datetime.fromisoformat(raw["ts"]),
            check=str(raw["check"]),
            context=str(raw.get("context", "unknown")),
            exit_code=int(raw["exit_code"]),
            duration_ms=int(raw.get("duration_ms", 0)),
            violations=int(raw.get("violations", 0)),
            rules=tuple(str(r) for r in raw.get("rules", [])),
        )
    except (ValueError, KeyError, TypeError):
        return None


def load_events(since_days: int | None = None) -> list[Event]:
    path = events_path()
    if not path.is_file():
        return []

    events: list[Event] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = _parse(line)
            if event is not None:
                events.append(event)

    if since_days is not None:
        threshold = datetime.now(tz=events[0].ts.tzinfo).astimezone() if events else None
        if threshold is not None:
            cutoff = threshold - timedelta(days=since_days)
            events = [e for e in events if e.ts >= cutoff]

    events.sort(key=lambda e: e.ts)
    return events


def check_stats(events: list[Event]) -> list[CheckStat]:
    runs: Counter[str] = Counter()
    blocks: Counter[str] = Counter()
    violations: Counter[str] = Counter()
    total_ms: Counter[str] = Counter()

    for event in events:
        runs[event.check] += 1
        total_ms[event.check] += event.duration_ms
        violations[event.check] += event.violations
        if event.blocked:
            blocks[event.check] += 1

    stats = [
        CheckStat(
            check=check,
            runs=count,
            blocks=blocks[check],
            violations=violations[check],
            total_ms=total_ms[check],
        )
        for check, count in runs.items()
    ]
    # 止めた回数の多い順。見直しの優先度そのもの
    stats.sort(key=lambda s: (-s.blocks, -s.runs, s.check))
    return stats


def rule_stats(events: list[Event]) -> list[RuleStat]:
    hits: Counter[str] = Counter()
    last: dict[str, datetime] = {}

    for event in events:
        for rule in event.rules:
            hits[rule] += 1
            if rule not in last or event.ts > last[rule]:
                last[rule] = event.ts

    stats = [
        RuleStat(rule=rule, hits=count, last_seen=last[rule].isoformat(timespec="seconds"))
        for rule, count in hits.items()
    ]
    stats.sort(key=lambda s: (-s.hits, s.rule))
    return stats


def daily_counts(events: list[Event], days: int = 30) -> list[dict[str, object]]:
    """日別の実行回数とブロック回数。推移を見て増減を判断する。"""
    if not events:
        return []

    blocks_by_day: Counter[date] = Counter()
    runs_by_day: Counter[date] = Counter()
    for event in events:
        day = event.ts.date()
        runs_by_day[day] += 1
        if event.blocked:
            blocks_by_day[day] += 1

    last_day = max(runs_by_day)
    span = [last_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    return [
        {
            "date": day.isoformat(),
            "runs": runs_by_day.get(day, 0),
            "blocks": blocks_by_day.get(day, 0),
        }
        for day in span
    ]


def silent_checks(stats: list[CheckStat]) -> list[CheckStat]:
    """一度も止めていない検査。剥がす候補として提示する。

    **「不要」とは断定しない。** 抑止力として効いている可能性があり、
    判断は人が行う。ここは候補を挙げるまでに留める。
    """
    return [s for s in stats if s.blocks == 0]
