from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from sns_collector.common.config import YouTubeConfig
from sns_collector.youtube import search as youtube_search


def _config(keywords: list[str]) -> YouTubeConfig:
    return YouTubeConfig(
        api_key="dummy",
        order="relevance",
        max_results_per_keyword=25,
        region_code="JP",
        relevance_language="ja",
        keywords=keywords,
    )


FAKE_ITEM = {
    "id": {"videoId": "abc123XYZ"},
    "snippet": {
        "publishedAt": "2026-07-20T12:00:00Z",
        "channelId": "UC12345",
        "title": "新規事業のアイデア特集",
        "description": "スタートアップ向けの解説動画です",
        "channelTitle": "Some Channel",
    },
}


def test_run_writes_new_videos_and_skips_duplicates(tmp_path: Path):
    config = YouTubeConfig(
        api_key="dummy",
        order="relevance",
        max_results_per_keyword=25,
        region_code="JP",
        relevance_language="ja",
        keywords=["新規事業 アイデア"],
    )
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with patch("sns_collector.youtube.search.search_videos", return_value=[FAKE_ITEM]):
        youtube_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["video_id"] == "abc123XYZ"
    assert record["title"] == "新規事業のアイデア特集"
    assert record["url"] == "https://www.youtube.com/watch?v=abc123XYZ"

    with patch("sns_collector.youtube.search.search_videos", return_value=[FAKE_ITEM]):
        youtube_search.run(config, data_dir=data_dir, db_path=db_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1


def test_failed_keyword_does_not_discard_other_results(tmp_path: Path):
    """1キーワードの取得失敗で、他キーワードの収集結果まで失われてはならない。

    YouTubeは1キーワードあたり100クオータユニットを消費するため、
    ここで落とすと消費済みクオータまで無駄になる。
    """
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(_api_key, keyword, *_args):
        if keyword == "失敗する語":
            raise requests.HTTPError("403 Client Error: Forbidden")
        return [FAKE_ITEM]

    with patch("sns_collector.youtube.search.search_videos", side_effect=fake_search):
        youtube_search.run(
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

    def fake_search(_api_key, keyword, *_args):
        if keyword == "壊れる語":
            raise RuntimeError("想定外の例外")
        return [FAKE_ITEM]

    with (
        patch("sns_collector.youtube.search.search_videos", side_effect=fake_search),
        pytest.raises(RuntimeError),
    ):
        youtube_search.run(_config(["成功する語", "壊れる語"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1, "例外の前に収集した分がディスクに書かれていない"
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_malformed_item_is_skipped_without_losing_others(tmp_path: Path):
    """必須フィールドを欠く動画があっても、その1件だけを捨てて処理を続ける。"""
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    broken_item = {k: v for k, v in FAKE_ITEM.items() if k != "id"}
    other_item = {**FAKE_ITEM, "id": {"videoId": "other456"}}

    with patch(
        "sns_collector.youtube.search.search_videos",
        return_value=[broken_item, FAKE_ITEM, other_item],
    ):
        youtube_search.run(_config(["キーワード"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 2
