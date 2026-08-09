from __future__ import annotations

from typing import Any

from ..common.http import get_json

SEARCH_URL = "https://oauth.reddit.com/search"

# OAuth APIはclient_idあたり100 req/min(10分平均)。2.0秒あれば十分に下回る
INTERVAL_SECONDS = 2.0


def search_posts(
    query: str, token: str, user_agent: str, limit: int, sort: str, time_filter: str
) -> list[dict[str, Any]]:
    """全サブレディット横断のキーワード検索。1ページのみ取得する(ページングはしない)。

    User-Agentは必須。requests既定の python-requests/x.y は Reddit側で遮断される。
    """
    payload = get_json(
        SEARCH_URL,
        params={
            "q": query,
            "limit": limit,
            "sort": sort,
            "t": time_filter,
            "type": "link",
            # 1を渡さないと本文中の&や<がHTMLエンティティで返る
            "raw_json": 1,
        },
        headers={"Authorization": f"Bearer {token}", "User-Agent": user_agent},
        interval=INTERVAL_SECONDS,
        label=f"reddit:{query}",
    )
    children = payload.get("data", {}).get("children", [])
    return [c.get("data", {}) for c in children if isinstance(c, dict)]
