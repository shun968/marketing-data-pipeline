from __future__ import annotations

from typing import Any

from ...http import get_json

SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def search_posts(query: str, sort: str, limit: int) -> list[dict[str, Any]]:
    """認証不要のBluesky公開検索API。1ページのみ取得する(ページングはしない)。"""
    payload = get_json(
        SEARCH_URL,
        params={"q": query, "sort": sort, "limit": limit},
        label=f"bluesky:{query}",
    )
    return payload.get("posts", [])
