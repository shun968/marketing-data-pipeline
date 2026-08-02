from __future__ import annotations

import pytest

# 収集済みJSONL 1行の形。db/adapters.py が読む入力そのもの
BLUESKY_RECORD = {
    "post_id": "at://did:plc:abc/app.bsky.feed.post/xyz",
    "keyword": "ラズパイ YOLO",
    "text": "動かない",
    "author_handle": "someone.bsky.social",
    "author_display_name": "Someone",
    "author_did": "did:plc:abc",
    "lang": ["ja"],
    "like_count": 3,
    "repost_count": 1,
    "reply_count": 0,
    "created_at": "2026-07-20T12:00:00.000Z",
    "indexed_at": "2026-07-20T12:00:05.000Z",
    "url": "https://bsky.app/profile/someone.bsky.social/post/xyz",
    "collected_at": "2026-08-02T00:00:00+00:00",
    "raw": {"uri": "at://did:plc:abc/app.bsky.feed.post/xyz"},
}

YOUTUBE_RECORD = {
    "video_id": "abc123",
    "keyword": "Jetson YOLO",
    "title": "タイトル",
    "description": "説明文",
    "channel_id": "UC123",
    "channel_title": "チャンネル",
    "published_at": "2026-07-20T12:00:00Z",
    "url": "https://www.youtube.com/watch?v=abc123",
    "collected_at": "2026-08-02T00:00:00+00:00",
    "raw": {"id": {"videoId": "abc123"}},
}


@pytest.fixture
def bluesky_record() -> dict:
    return dict(BLUESKY_RECORD)


@pytest.fixture
def youtube_record() -> dict:
    return dict(YOUTUBE_RECORD)
