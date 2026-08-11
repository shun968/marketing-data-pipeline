from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....domain.collect import CollectTask, Record
from ....domain.config import RedditConfig
from ...http import source_errors
from .auth import TokenProvider
from .client import search_posts
from .dto import RedditPost


def tasks(
    config: RedditConfig, collected_at: datetime, notify: Callable[[str], None]
) -> list[CollectTask]:
    provider = TokenProvider(config.client_id, config.client_secret, config.user_agent)

    # トークンを先に1回取る。ここで失敗したら1キーワードも叩かずに終える。
    # まだ何も書いていないため、失われる収集データは無い
    with source_errors():
        provider.token()

    return [_task(config, provider, keyword, collected_at) for keyword in config.keywords]


def _task(
    config: RedditConfig, provider: TokenProvider, keyword: str, collected_at: datetime
) -> CollectTask:
    def fetch() -> list[dict]:
        with source_errors():
            return search_posts(
                keyword,
                provider.token(),
                config.user_agent,
                config.limit_per_keyword,
                config.sort,
                config.time_filter,
            )

    def parse(raw: dict) -> Record:
        post = RedditPost.from_post(raw, keyword, collected_at)
        return Record(native_id=post.post_id, payload=post.to_dict())

    return CollectTask(label=f"reddit:{keyword}", keyword=keyword, fetch=fetch, parse=parse)
