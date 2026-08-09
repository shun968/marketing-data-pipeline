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

HACKERNEWS_RECORD = {
    "item_id": "49217777",
    "keyword": '"jetson nano"',
    "text": "困っている\nJetson Nanoでの推論が遅い",
    "title": "困っている",
    "item_type": "comment",
    "author": "someone",
    "points": 3,
    "num_comments": 0,
    "story_id": "49216362",
    "created_at": "2026-08-08T00:33:37Z",
    "url": "https://news.ycombinator.com/item?id=49217777",
    "collected_at": "2026-08-08T00:00:00+00:00",
    "raw": {"objectID": "49217777", "_tags": ["comment"]},
}

GITHUB_RECORD = {
    "issue_id": "2345678901",
    "keyword": "collision avoidance",
    "text": "衝突回避のログが読みにくい\n本文だよ",
    "title": "衝突回避のログが読みにくい",
    "body": "本文だよ",
    "repo_full_name": "owner/repo",
    "number": 42,
    "state": "open",
    "author": "someone",
    "author_id": "9999",
    "comments": 3,
    "reactions": 1,
    "labels": ["bug", "help wanted"],
    "created_at": "2026-08-08T00:33:37Z",
    "updated_at": "2026-08-08T01:00:00Z",
    "url": "https://github.com/owner/repo/issues/42",
    "collected_at": "2026-08-08T00:00:00+00:00",
    "raw": {"id": 2345678901, "number": 42},
}

REDDIT_RECORD = {
    "post_id": "t3_1abcdef",
    "keyword": "collision avoidance ship",
    "text": "タイトル\n本文だよ",
    "title": "タイトル",
    "selftext": "本文だよ",
    "subreddit": "maritime",
    "author": "someone",
    "author_id": "t2_1234",
    "score": 12,
    "num_comments": 4,
    "upvote_ratio": 0.9,
    "created_at": "2025-08-08T00:33:37+00:00",
    "url": "https://www.reddit.com/r/maritime/comments/1abcdef/",
    "link_url": None,
    "collected_at": "2026-08-08T00:00:00+00:00",
    "raw": {"name": "t3_1abcdef"},
}


@pytest.fixture
def bluesky_record() -> dict:
    return dict(BLUESKY_RECORD)


@pytest.fixture
def youtube_record() -> dict:
    return dict(YOUTUBE_RECORD)


@pytest.fixture
def hackernews_record() -> dict:
    return dict(HACKERNEWS_RECORD)


@pytest.fixture
def github_record() -> dict:
    return dict(GITHUB_RECORD)


@pytest.fixture
def reddit_record() -> dict:
    return dict(REDDIT_RECORD)
