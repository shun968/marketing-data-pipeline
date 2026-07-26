from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..common.config import YouTubeConfig
from ..common.seen_store import SeenStore
from ..common.storage import append_jsonl
from .client import search_videos
from .models import YouTubeVideo


def run(config: YouTubeConfig, data_dir: Path, state_path: Path) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    seen_store = SeenStore(state_path, today=today)
    run_seen: set[str] = set()
    new_videos: list[YouTubeVideo] = []

    for keyword in config.keywords:
        items = search_videos(
            config.api_key,
            keyword,
            config.order,
            config.max_results_per_keyword,
            config.region_code,
            config.relevance_language,
        )
        new_count = 0
        skip_count = 0
        for item in items:
            video = YouTubeVideo.from_item(item, keyword, collected_at)
            if video.video_id in run_seen or not seen_store.is_new(video.video_id):
                skip_count += 1
                continue
            run_seen.add(video.video_id)
            seen_store.mark_seen(video.video_id)
            new_videos.append(video)
            new_count += 1
        print(
            f"[youtube:{keyword}] 取得: {len(items)}件 "
            f"/ 新規: {new_count}件 / スキップ: {skip_count}件"
        )

    output_path = append_jsonl([v.to_dict() for v in new_videos], data_dir, today)
    seen_store.save()
    print(f"合計 {len(new_videos)} 件を {output_path} に保存しました。")
