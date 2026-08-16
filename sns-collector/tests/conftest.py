from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from sns_collector.adapter.config_file import ENV_FILE_VAR

# 設定読み取りが見る秘匿系の環境変数。下の fixture の対象
SECRET_ENV_VARS = (
    "YOUTUBE_API_KEY",
    "GITHUB_TOKEN",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
)


@pytest.fixture(autouse=True)
def 環境変数を持ち込まない() -> Iterator[None]:
    """実行環境の鍵と `SNS_COLLECTOR_ENV_FILE` を、全テストから隔離する。

    **モジュール単位ではなくここに置く。** 鍵の置き場を外部化して以降、
    開発者のシェルに `SNS_COLLECTOR_ENV_FILE` が入っているのが通常の状態に
    なった（sns-collector/README.md）。設定を読むテストはどのファイルにもあり、
    片方のモジュールだけで消しても、もう片方が環境依存で落ちる。

    後片付けを monkeypatch に任せない理由: `load_dotenv` がテスト中に入れた
    変数は monkeypatch の巻き戻し対象にならず、後続のテストへ漏れる。
    """
    saved = {name: os.environ.pop(name, None) for name in (ENV_FILE_VAR, *SECRET_ENV_VARS)}
    try:
        yield
    finally:
        # テスト中に入った値は残さない。消した値だけを戻す
        for name in (ENV_FILE_VAR, *SECRET_ENV_VARS):
            os.environ.pop(name, None)
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


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

HNJOBS_RECORD = {
    "item_id": "49175131",
    "keyword": "embedded",
    "text": "Ask HN: Who is hiring? (August 2026)\nBrightcore Energy | Embedded Engineer",
    "thread_id": "49156683",
    "thread_title": "Ask HN: Who is hiring? (August 2026)",
    "thread_kind": "hiring",
    "seeking": None,
    "author": "bzimm",
    "created_at": "2026-08-05T12:00:00Z",
    "url": "https://news.ycombinator.com/item?id=49175131",
    "collected_at": "2026-08-11T00:00:00+00:00",
    "raw": {"objectID": "49175131", "parent_id": 49156683},
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
