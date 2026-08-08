from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(value: Any) -> str | None:
    """AlgoliaのHTML断片(<p>やHTMLエンティティ)をプレーンテキストへ。

    story_text / comment_text はコメント投稿時のHTMLをそのまま含む。
    タグを残すと本文の判定・要約に無関係なノイズになる。
    """
    if not isinstance(value, str) or not value:
        return None
    text = html.unescape(_TAG_RE.sub("", value)).strip()
    return text or None


@dataclass(frozen=True)
class HackerNewsItem:
    item_id: str
    keyword: str
    text: str
    title: str | None
    item_type: str
    author: str
    points: int
    num_comments: int
    story_id: str | None
    created_at: str
    url: str
    collected_at: str
    raw: dict[str, Any]

    @classmethod
    def from_hit(cls, hit: dict[str, Any], keyword: str, collected_at: datetime) -> HackerNewsItem:
        item_id = hit["objectID"]
        tags = hit.get("_tags", [])
        item_type = "comment" if "comment" in tags else "story"

        # コメントは自分のtitleを持たない。story_title(親ストーリーの見出し)を
        # 文脈として text に含める。無いとコメント単体では何の話か分からない
        title = hit.get("title") or None
        topic = title or hit.get("story_title") or None
        body = _clean_html(hit.get("story_text")) or _clean_html(hit.get("comment_text"))
        text = "\n".join(part for part in (topic, body) if part)

        story_id = hit.get("story_id")

        if item_type == "comment":
            url = f"https://news.ycombinator.com/item?id={item_id}"
        else:
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={item_id}"

        return cls(
            item_id=item_id,
            keyword=keyword,
            text=text,
            title=title,
            item_type=item_type,
            author=hit.get("author", ""),
            points=hit.get("points") or 0,
            num_comments=hit.get("num_comments") or 0,
            story_id=str(story_id) if story_id is not None else None,
            created_at=hit.get("created_at", ""),
            url=url,
            collected_at=collected_at.isoformat(),
            # _tags・parent_id等、平坦化で落ちた情報を後から使えるように残す
            raw=hit,
        )

    def to_dict(self) -> dict:
        return asdict(self)
