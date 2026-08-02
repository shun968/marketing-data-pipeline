"""ADRの読み取り。

ADRの目的は「今どの決定が有効かを後から素早く把握できること」にある。
一覧はステータス順に並べ、有効なもの(採用)を先頭へ置く。

書式は scripts/check-adr-format.sh が強制しているため、ここでは
書式違反を検査しない。**壊れた入力は落とさず「不明」として表示する。**
検査は検査で行い、閲覧はどんな状態でも見えることを優先する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from dashboard import markup
from dashboard.paths import roots

# scripts/check-adr-format.sh が強制する語彙。表示順もこの並びに従う
STATUS_ORDER = ["採用", "提案中", "非推奨", "却下", "不明"]

_TITLE = re.compile(r"^#\s+(ADR-(\d{4})):\s*(.+?)\s*$")
_STATUS = re.compile(r"^-\s*ステータス:\s*(.+?)\s*$", re.MULTILINE)
_DATE = re.compile(r"^-\s*日付:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
_SUPERSEDED = re.compile(r"^置換済み（(ADR-\d{4})）$")


@dataclass(frozen=True)
class Adr:
    slug: str
    number: str
    title: str
    status: str
    superseded_by: str | None
    date: str
    body: str
    path: str

    @property
    def is_active(self) -> bool:
        return self.status == "採用"

    @property
    def status_key(self) -> str:
        """並べ替え・絞り込みの単位。置換済みは1つのまとまりとして扱う。"""
        return "置換済み" if self.superseded_by else self.status


def _parse(path: Path) -> Adr:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    number = ""
    title = path.stem
    if lines:
        matched = _TITLE.match(lines[0])
        if matched:
            number, title = matched.group(2), matched.group(3)

    status_match = _STATUS.search(text)
    raw_status = status_match.group(1) if status_match else "不明"

    superseded = _SUPERSEDED.match(raw_status)
    status = "置換済み" if superseded else raw_status
    superseded_by = superseded.group(1) if superseded else None

    date_match = _DATE.search(text)

    return Adr(
        slug=path.stem,
        number=number,
        title=title,
        status=status,
        superseded_by=superseded_by,
        date=date_match.group(1) if date_match else "",
        body=text,
        path=f"docs/adr/{path.name}",
    )


def load_all() -> list[Adr]:
    directory = roots().adr
    if not directory.is_dir():
        return []

    items = [_parse(path) for path in sorted(directory.glob("*.md")) if path.name != "README.md"]
    return sorted(items, key=lambda a: a.slug)


def load(slug: str) -> Adr | None:
    for item in load_all():
        if item.slug == slug:
            return item
    return None


def render_body(item: Adr) -> str:
    return markup.render(item.body)


def group_by_status(items: list[Adr]) -> list[tuple[str, list[Adr]]]:
    """ステータス別にまとめる。順序は STATUS_ORDER に従う。

    置換済みは末尾へ置く。読み手が最初に知りたいのは「今有効なもの」であり、
    履歴は後から辿れれば足りる。
    """
    buckets: dict[str, list[Adr]] = {}
    for item in items:
        buckets.setdefault(item.status_key, []).append(item)

    order = [*STATUS_ORDER, "置換済み"]
    known = [(status, buckets.pop(status)) for status in order if status in buckets]
    # 語彙外のステータスも落とさず末尾に出す（検査で弾かれる前の状態を見たい）
    unknown = sorted(buckets.items())
    return known + unknown
