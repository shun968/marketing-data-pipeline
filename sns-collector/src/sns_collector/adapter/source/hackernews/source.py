from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....domain.collect import CollectTask, Record
from ....domain.config import HackerNewsConfig
from ...http import source_errors
from .client import search_items
from .dto import HackerNewsItem


def tasks(
    config: HackerNewsConfig, collected_at: datetime, notify: Callable[[str], None]
) -> list[CollectTask]:
    return [_task(config, keyword, collected_at) for keyword in config.keywords]


def _task(config: HackerNewsConfig, keyword: str, collected_at: datetime) -> CollectTask:
    def fetch() -> list[dict]:
        with source_errors():
            return search_items(keyword, config.tags, config.hits_per_page)

    def parse(raw: dict) -> Record:
        item = HackerNewsItem.from_hit(raw, keyword, collected_at)
        return Record(native_id=item.item_id, payload=item.to_dict())

    return CollectTask(label=f"hackernews:{keyword}", keyword=keyword, fetch=fetch, parse=parse)
