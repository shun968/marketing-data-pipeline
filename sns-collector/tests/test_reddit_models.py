from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sns_collector.reddit.models import RedditPost

COLLECTED_AT = datetime(2026, 8, 8, tzinfo=UTC)

FAKE_POST = {
    "name": "t3_1abcdef",
    "title": "タイトル",
    "selftext": "本文だよ",
    "subreddit": "maritime",
    "author": "someone",
    "author_fullname": "t2_1234",
    "score": 12,
    "num_comments": 4,
    "upvote_ratio": 0.9,
    "created_utc": 1754611200.0,
    "permalink": "/r/maritime/comments/1abcdef/",
    "url": "https://www.reddit.com/r/maritime/comments/1abcdef/",
}


def test_fullnameをpost_idに使う():
    item = RedditPost.from_post(FAKE_POST, "kw", COLLECTED_AT)
    assert item.post_id == "t3_1abcdef"


def test_created_utcのepochをISO8601へ変換する():
    item = RedditPost.from_post(FAKE_POST, "kw", COLLECTED_AT)
    assert item.created_at == datetime.fromtimestamp(1754611200.0, tz=UTC).isoformat()
    assert item.created_at.endswith("+00:00"), "UTC固定。実行機のTZに依存しない"


def test_created_utcが読めなくても投稿を捨てない():
    item = RedditPost.from_post({**FAKE_POST, "created_utc": None}, "kw", COLLECTED_AT)
    assert item.created_at == ""


def test_permalinkからURLを組み立てる():
    item = RedditPost.from_post(FAKE_POST, "kw", COLLECTED_AT)
    assert item.url == "https://www.reddit.com/r/maritime/comments/1abcdef/"


def test_selftextが空のリンク投稿は本文がタイトルだけになる():
    item = RedditPost.from_post({**FAKE_POST, "selftext": ""}, "kw", COLLECTED_AT)
    assert item.text == "タイトル"
    assert item.selftext is None


def test_削除済み投稿者でもauthor_idがNoneで読める():
    item = RedditPost.from_post(
        {**FAKE_POST, "author": "[deleted]", "author_fullname": None}, "kw", COLLECTED_AT
    )
    assert item.author_id is None
    assert item.author == "[deleted]"


def test_必須フィールドが無ければ例外():
    with pytest.raises(KeyError):
        RedditPost.from_post({"title": "タイトル"}, "kw", COLLECTED_AT)
