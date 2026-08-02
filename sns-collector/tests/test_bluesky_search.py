from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
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
    db_path = tmp_path / "data" / "analysis.duckdb"

    with patch("sns_collector.bluesky.search.search_posts", return_value=[FAKE_POST]):
        bluesky_search.run(config, data_dir=data_dir, db_path=db_path)

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
        bluesky_search.run(config, data_dir=data_dir, db_path=db_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1


def test_failed_keyword_does_not_discard_other_results(tmp_path: Path):
    """1キーワードの取得失敗で、他キーワードの収集結果まで失われてはならない。"""
    config = BlueskyConfig(
        sort="latest", limit_per_keyword=50, keywords=["成功する語", "失敗する語"]
    )
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword: str, *_args):
        if keyword == "失敗する語":
            raise requests.HTTPError("403 Client Error: Forbidden")
        return [FAKE_POST]

    with patch("sns_collector.bluesky.search.search_posts", side_effect=fake_search):
        bluesky_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "失敗したキーワードより前の収集結果が保存されていない"
    assert db_path.exists(), "分析DBが作られていない"


def test_unexpected_exception_does_not_discard_saved_results(tmp_path: Path):
    """想定外の例外がrunを貫通しても、それ以前の収集結果は保存済みでなければならない。

    保存をrun末尾の一括のみにすると、ここで全件を失う(#8で実際に201件を失った)。
    RequestException以外の例外でも成立することを担保する。
    """
    config = BlueskyConfig(sort="latest", limit_per_keyword=50, keywords=["成功する語", "壊れる語"])
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword: str, *_args):
        if keyword == "壊れる語":
            raise RuntimeError("想定外の例外")
        return [FAKE_POST]

    with (
        patch("sns_collector.bluesky.search.search_posts", side_effect=fake_search),
        pytest.raises(RuntimeError),
    ):
        bluesky_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1, "例外の前に収集した分がディスクに書かれていない"
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_malformed_post_is_skipped_without_losing_others(tmp_path: Path):
    """必須フィールドを欠く投稿があっても、その1件だけを捨てて処理を続ける。

    BlueskyPost.from_post は post["uri"] を subscript で読むためKeyErrorが起きうる。
    これがrunを貫通すると、同一キーワード内の他の投稿まで失われる。
    """
    config = BlueskyConfig(sort="latest", limit_per_keyword=50, keywords=["キーワード"])
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    broken_post = {k: v for k, v in FAKE_POST.items() if k != "uri"}
    other_post = {**FAKE_POST, "uri": "at://did:plc:abc123/app.bsky.feed.post/other"}

    with patch(
        "sns_collector.bluesky.search.search_posts",
        return_value=[broken_post, FAKE_POST, other_post],
    ):
        bluesky_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "不正な投稿以外の2件が保存されていない"


def test_no_new_posts_does_not_create_empty_file(tmp_path: Path):
    """新規がゼロのとき、空のJSONLを作らない。"""
    config = BlueskyConfig(sort="latest", limit_per_keyword=50, keywords=["キーワード"])
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with patch("sns_collector.bluesky.search.search_posts", return_value=[]):
        bluesky_search.run(config, data_dir=data_dir, db_path=db_path)

    assert list(data_dir.glob("*.jsonl")) == []
