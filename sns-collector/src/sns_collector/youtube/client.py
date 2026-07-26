from __future__ import annotations

from typing import Any

import requests

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
TIMEOUT_SECONDS = 15


def search_videos(
    api_key: str,
    query: str,
    order: str,
    max_results: int,
    region_code: str,
    relevance_language: str,
) -> list[dict[str, Any]]:
    response = requests.get(
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
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("items", [])
