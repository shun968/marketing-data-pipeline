from __future__ import annotations

from typing import Any

import requests

SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
TIMEOUT_SECONDS = 15


def search_posts(query: str, sort: str, limit: int) -> list[dict[str, Any]]:
    """認証不要のBluesky公開検索API。1ページのみ取得する(ページングはしない)。"""
    response = requests.get(
        SEARCH_URL,
        params={"q": query, "sort": sort, "limit": limit},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("posts", [])
