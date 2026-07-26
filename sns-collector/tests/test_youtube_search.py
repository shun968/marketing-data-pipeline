from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sns_collector.common.config import YouTubeConfig
from sns_collector.youtube import search as youtube_search

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
    state_path = tmp_path / "state" / "youtube_seen.json"

    with patch("sns_collector.youtube.search.search_videos", return_value=[FAKE_ITEM]):
        youtube_search.run(config, data_dir=data_dir, state_path=state_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["video_id"] == "abc123XYZ"
    assert record["title"] == "新規事業のアイデア特集"
    assert record["url"] == "https://www.youtube.com/watch?v=abc123XYZ"

    with patch("sns_collector.youtube.search.search_videos", return_value=[FAKE_ITEM]):
        youtube_search.run(config, data_dir=data_dir, state_path=state_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1
