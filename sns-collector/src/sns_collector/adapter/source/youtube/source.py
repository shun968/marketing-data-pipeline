from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....domain.collect import CollectTask, Record
from ....domain.config import YouTubeConfig
from ...http import source_errors
from .client import search_videos
from .dto import YouTubeVideo


def tasks(
    config: YouTubeConfig, collected_at: datetime, notify: Callable[[str], None]
) -> list[CollectTask]:
    return [_task(config, keyword, collected_at) for keyword in config.keywords]


def _task(config: YouTubeConfig, keyword: str, collected_at: datetime) -> CollectTask:
    def fetch() -> list[dict]:
        # 1キーワードの失敗で run 全体を落とさない。ここで落とすと消費済みクォータが無駄になる
        with source_errors():
            return search_videos(
                config.api_key,
                keyword,
                config.order,
                config.max_results_per_keyword,
                config.region_code,
                config.relevance_language,
            )

    def parse(raw: dict) -> Record:
        video = YouTubeVideo.from_item(raw, keyword, collected_at)
        return Record(native_id=video.video_id, payload=video.to_dict())

    return CollectTask(label=f"youtube:{keyword}", keyword=keyword, fetch=fetch, parse=parse)
