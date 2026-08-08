from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from sns_collector.common.config import HackerNewsConfig
from sns_collector.hackernews import search as hackernews_search


def _config(keywords: list[str]) -> HackerNewsConfig:
    return HackerNewsConfig(tags="(story,comment)", hits_per_page=50, keywords=keywords)


FAKE_HIT = {
    "objectID": "49217777",
    "author": "someone",
    "created_at": "2026-08-08T00:33:37Z",
    "points": 3,
    "num_comments": 0,
    "story_id": 49216362,
    "story_title": "困っている",
    "comment_text": "Jetson Nanoでの推論が遅い",
    "_tags": ["comment"],
}


def test_run_writes_new_items_and_skips_duplicates(tmp_path: Path):
    config = _config(['"jetson nano"'])
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with patch("sns_collector.hackernews.search.search_items", return_value=[FAKE_HIT]):
        hackernews_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["item_id"] == "49217777"
    assert record["item_type"] == "comment"
    assert record["url"] == "https://news.ycombinator.com/item?id=49217777"

    with patch("sns_collector.hackernews.search.search_items", return_value=[FAKE_HIT]):
        hackernews_search.run(config, data_dir=data_dir, db_path=db_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1


def test_failed_keyword_does_not_discard_other_results(tmp_path: Path):
    """1キーワードの取得失敗で、他キーワードの収集結果まで失われてはならない。"""
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword, *_args):
        if keyword == "失敗する語":
            raise requests.HTTPError("503 Server Error")
        return [FAKE_HIT]

    with patch("sns_collector.hackernews.search.search_items", side_effect=fake_search):
        hackernews_search.run(
            _config(["成功する語", "失敗する語"]), data_dir=data_dir, db_path=db_path
        )

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1
    assert db_path.exists(), "分析DBが作られていない"


def test_unexpected_exception_does_not_discard_saved_results(tmp_path: Path):
    """想定外の例外がrunを貫通しても、それ以前の収集結果は保存済みでなければならない。"""
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword, *_args):
        if keyword == "壊れる語":
            raise RuntimeError("想定外の例外")
        return [FAKE_HIT]

    with (
        patch("sns_collector.hackernews.search.search_items", side_effect=fake_search),
        pytest.raises(RuntimeError),
    ):
        hackernews_search.run(
            _config(["成功する語", "壊れる語"]), data_dir=data_dir, db_path=db_path
        )

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1, "例外の前に収集した分がディスクに書かれていない"
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_malformed_item_is_skipped_without_losing_others(tmp_path: Path):
    """必須フィールド(objectID)を欠く投稿があっても、その1件だけを捨てて処理を続ける。"""
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    broken_hit = {k: v for k, v in FAKE_HIT.items() if k != "objectID"}
    other_hit = {**FAKE_HIT, "objectID": "other456"}

    with patch(
        "sns_collector.hackernews.search.search_items",
        return_value=[broken_hit, FAKE_HIT, other_hit],
    ):
        hackernews_search.run(_config(["キーワード"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 2
