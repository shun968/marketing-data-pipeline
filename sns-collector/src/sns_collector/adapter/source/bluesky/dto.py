from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BlueskyPost:
    post_id: str
    keyword: str
    text: str
    author_handle: str
    author_display_name: str
    author_did: str
    lang: list[str]
    like_count: int
    repost_count: int
    reply_count: int
    created_at: str
    indexed_at: str
    url: str
    collected_at: str
    raw: dict[str, Any]

    @classmethod
    def from_post(cls, post: dict[str, Any], keyword: str, collected_at: datetime) -> BlueskyPost:
        uri = post["uri"]
        author = post.get("author", {})
        handle = author.get("handle", "")
        rkey = uri.rsplit("/", 1)[-1]
        record = post.get("record", {})

        return cls(
            post_id=uri,
            keyword=keyword,
            text=record.get("text", ""),
            author_handle=handle,
            author_display_name=author.get("displayName", ""),
            # ハンドルは改名で変わる。DIDは変わらないため、著者の同一性はこちらで見る
            author_did=author.get("did", ""),
            lang=record.get("langs", []),
            like_count=post.get("likeCount", 0),
            repost_count=post.get("repostCount", 0),
            reply_count=post.get("replyCount", 0),
            created_at=record.get("createdAt", ""),
            indexed_at=post.get("indexedAt", ""),
            url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            collected_at=collected_at.isoformat(),
            # 平坦化で落ちた情報（埋め込みカード・返信先・facets等）を後から使えるように残す。
            # 収集し直しは効かないため、取れるものは取れるうちに保存する（F-02）
            raw=post,
        )

    def to_dict(self) -> dict:
        return asdict(self)
