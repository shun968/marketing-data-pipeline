from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


def _epoch_to_iso(value: Any) -> str:
    """created_utc(epoch秒)をISO8601へ。読めなければ空文字。

    日時が読めないことは投稿を捨てる理由にならない(db/adapters.pyの方針と揃える)。
    """
    if not isinstance(value, int | float):
        return ""
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    except (ValueError, OSError, OverflowError):
        return ""


@dataclass(frozen=True)
class RedditPost:
    post_id: str
    keyword: str
    text: str
    title: str
    selftext: str | None
    subreddit: str
    author: str
    author_id: str | None
    score: int
    num_comments: int
    upvote_ratio: float | None
    created_at: str
    url: str
    link_url: str | None
    collected_at: str
    raw: dict[str, Any]

    @classmethod
    def from_post(cls, post: dict[str, Any], keyword: str, collected_at: datetime) -> RedditPost:
        post_id = post["name"]
        title = post.get("title") or ""
        selftext = post.get("selftext") or None
        text = "\n".join(part for part in (title, selftext) if part)
        permalink = post.get("permalink", "")

        return cls(
            post_id=post_id,
            keyword=keyword,
            text=text,
            title=title,
            selftext=selftext,
            subreddit=post.get("subreddit", ""),
            author=post.get("author", "") or "[deleted]",
            author_id=post.get("author_fullname") or None,
            score=post.get("score") or 0,
            num_comments=post.get("num_comments") or 0,
            upvote_ratio=post.get("upvote_ratio"),
            created_at=_epoch_to_iso(post.get("created_utc")),
            url=f"https://www.reddit.com{permalink}" if permalink else "",
            link_url=post.get("url") or None,
            collected_at=collected_at.isoformat(),
            raw=post,
        )

    def to_dict(self) -> dict:
        return asdict(self)
