from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import requests

from sns_collector.bluesky import search as bluesky_search
from sns_collector.common.config import BlueskyConfig

FAKE_POST = {
    "uri": "at://did:plc:abc123/app.bsky.feed.post/xyz789",
    "cid": "bafyxyz",
    "author": {
        "did": "did:plc:abc123",
        "handle": "someone.bsky.social",
        "displayName": "Someone",
    },
    "record": {
        "text": "新規事業のアイデアを探しています",
        "createdAt": "2026-07-20T12:00:00.000Z",
    },
    "likeCount": 3,
    "repostCount": 1,
    "replyCount": 0,
    "indexedAt": "2026-07-20T12:00:05.000Z",
}


def test_run_writes_new_posts_and_skips_duplicates(tmp_path: Path):
    config = BlueskyConfig(sort="latest", limit_per_keyword=50, keywords=["新規事業"])
    data_dir = tmp_path / "data"
    state_path = tmp_path / "state" / "bluesky_seen.json"

    with patch("sns_collector.bluesky.search.search_posts", return_value=[FAKE_POST]):
        bluesky_search.run(config, data_dir=data_dir, state_path=state_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["post_id"] == FAKE_POST["uri"]
    assert record["author_handle"] == "someone.bsky.social"
    assert record["url"] == "https://bsky.app/profile/someone.bsky.social/post/xyz789"

    # 2回目の実行では既知の投稿としてスキップされ、新規追記は発生しない
    with patch("sns_collector.bluesky.search.search_posts", return_value=[FAKE_POST]):
        bluesky_search.run(config, data_dir=data_dir, state_path=state_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1


def test_failed_keyword_does_not_discard_other_results(tmp_path: Path):
    """1キーワードの取得失敗で、他キーワードの収集結果まで失われてはならない。"""
    config = BlueskyConfig(
        sort="latest", limit_per_keyword=50, keywords=["成功する語", "失敗する語"]
    )
    data_dir = tmp_path / "data"
    state_path = tmp_path / "state" / "bluesky_seen.json"

    def fake_search(keyword: str, *_args):
        if keyword == "失敗する語":
            raise requests.HTTPError("403 Client Error: Forbidden")
        return [FAKE_POST]

    with patch("sns_collector.bluesky.search.search_posts", side_effect=fake_search):
        bluesky_search.run(config, data_dir=data_dir, state_path=state_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "失敗したキーワードより前の収集結果が保存されていない"
    assert state_path.exists(), "SeenStoreが保存されていない"
