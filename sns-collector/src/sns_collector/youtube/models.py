from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    keyword: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: str
    url: str
    collected_at: str
    raw: dict[str, Any]

    @classmethod
    def from_item(cls, item: dict[str, Any], keyword: str, collected_at: datetime) -> YouTubeVideo:
        video_id = item["id"]["videoId"]
        snippet = item.get("snippet", {})

        return cls(
            video_id=video_id,
            keyword=keyword,
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            published_at=snippet.get("publishedAt", ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
            collected_at=collected_at.isoformat(),
            # サムネイル・ライブ配信フラグ等、平坦化で落ちる情報を残す。
            # 収集し直しはクォータを食うため、取れるうちに保存する（F-02）
            raw=item,
        )

    def to_dict(self) -> dict:
        return asdict(self)
