from __future__ import annotations

from typing import Any

from ...http import get_json

# Algolia が提供する非公式・認証不要の検索API。公式Firebase API
# (hacker-news.firebaseio.com) はID指定の取得とtop/new等の固定リストしか
# 提供せず、全文検索ができない。search_by_date は新着順（Blueskyのlatestと
# 対応する取り方）。
SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


def search_items(query: str, tags: str, hits_per_page: int) -> list[dict[str, Any]]:
    """認証不要のHacker News検索API(Algolia)。1ページのみ取得する(ページングはしない)。"""
    payload = get_json(
        SEARCH_URL,
        params={"query": query, "tags": tags, "hitsPerPage": hits_per_page},
        label=f"hackernews:{query}",
    )
    return payload.get("hits", [])
