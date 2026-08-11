"""収集した投稿の共通形。

収集元ごとのDTO（`adapter/source/*/dto.py`）は外部APIの形に従うが、
`posts` テーブルへ入る形はここに1つだけある。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class MappingError(ValueError):
    """収集元の1行を共通形へ落とせない。呼び出し側はこの行だけを捨てる。"""


@dataclass(frozen=True)
class PostRow:
    id: str
    platform: str
    native_id: str
    author_id: str | None
    author_handle: str | None
    text: str
    url: str | None
    lang: str | None
    posted_at: datetime | None
    collected_at: datetime | None
    matched_keywords: list[str]
    metrics: str
    raw: str
