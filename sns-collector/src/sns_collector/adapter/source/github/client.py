from __future__ import annotations

from typing import Any

from ...http import get_json

SEARCH_URL = "https://api.github.com/search/issues"

# 検索APIのレート制限は他のGitHub APIより桁違いに低い。
#   未認証: 10 req/min -> 6.0秒以上。余裕を見て6.5秒
#   認証済: 30 req/min -> 2.0秒以上。余裕を見て2.5秒
# APIの性質であって利用者の設定ではないため、keywords.yamlへは出さない
INTERVAL_WITHOUT_TOKEN = 6.5
INTERVAL_WITH_TOKEN = 2.5

API_VERSION = "2022-11-28"
USER_AGENT = "sns-collector"


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_issues(
    query: str, qualifiers: str, per_page: int, token: str | None
) -> list[dict[str, Any]]:
    """GitHub Issue検索。1ページのみ取得する(ページングはしない)。"""
    payload = get_json(
        SEARCH_URL,
        params={
            "q": f"{query} {qualifiers}".strip(),
            "per_page": per_page,
            "sort": "created",
            "order": "desc",
        },
        headers=_headers(token),
        interval=INTERVAL_WITH_TOKEN if token else INTERVAL_WITHOUT_TOKEN,
        label=f"github:{query}",
    )
    # "items"キー自体がnullで返る場合があるため`or []`で吸収する。`.get("items", [])`
    # だとキーが存在しnullのときに既定値が使われず、呼び出し側のfor文がTypeErrorで
    # 落ちる(search.pyのrequests.RequestException隔離をすり抜ける)
    return payload.get("items") or []
