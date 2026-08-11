from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....domain.collect import CollectTask, Record
from ....domain.config import BlueskyConfig
from ...http import source_errors
from .client import search_posts
from .dto import BlueskyPost


def tasks(
    config: BlueskyConfig, collected_at: datetime, notify: Callable[[str], None]
) -> list[CollectTask]:
    return [_task(config, keyword, collected_at) for keyword in config.keywords]


def _task(config: BlueskyConfig, keyword: str, collected_at: datetime) -> CollectTask:
    def fetch() -> list[dict]:
        with source_errors():
            return search_posts(keyword, config.sort, config.limit_per_keyword)

    def parse(raw: dict) -> Record:
        post = BlueskyPost.from_post(raw, keyword, collected_at)
        return Record(native_id=post.post_id, payload=post.to_dict())

    return CollectTask(label=f"bluesky:{keyword}", keyword=keyword, fetch=fetch, parse=parse)
