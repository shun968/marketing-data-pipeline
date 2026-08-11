from __future__ import annotations

from typing import Any

from ...http import get_json

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def search_videos(
    api_key: str,
    query: str,
    order: str,
    max_results: int,
    region_code: str,
    relevance_language: str,
) -> list[dict[str, Any]]:
    payload = get_json(
        SEARCH_URL,
        params={
            "key": api_key,
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": order,
            "maxResults": max_results,
            "regionCode": region_code,
            "relevanceLanguage": relevance_language,
        },
        label=f"youtube:{query}",
    )
    return payload.get("items", [])
