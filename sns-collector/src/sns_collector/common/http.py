from __future__ import annotations

import time
from typing import Any

import requests

TIMEOUT_SECONDS = 15

# 連続リクエストの間隔。キーワード数が増えるとAPI側のスロットリングに掛かるため、
# 1リクエストごとに必ずこの秒数を空ける。
REQUEST_INTERVAL_SECONDS = 1.0

# 一時的な失敗とみなして再試行するステータス。
# Blueskyは連続アクセス時のスロットリングを 429 ではなく 403 で返すことがある。
RETRYABLE_STATUS = frozenset({403, 429, 500, 502, 503, 504})

MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 2.0


def get_json(
    url: str,
    params: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = TIMEOUT_SECONDS,
    interval: float = REQUEST_INTERVAL_SECONDS,
    max_attempts: int = MAX_ATTEMPTS,
    label: str = "",
) -> dict[str, Any]:
    """レート制限に配慮したGET。一時的な失敗は指数バックオフで再試行する。

    再試行しても回復しない場合、および再試行対象外のステータスの場合は
    HTTPError を送出する。呼び出し側でキーワード単位に捕捉すること。
    """
    return _request_json(
        "GET",
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        interval=interval,
        max_attempts=max_attempts,
        label=label,
    )


def post_json(
    url: str,
    *,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = TIMEOUT_SECONDS,
    interval: float = REQUEST_INTERVAL_SECONDS,
    max_attempts: int = MAX_ATTEMPTS,
    label: str = "",
) -> dict[str, Any]:
    """レート制限に配慮したPOST。挙動はget_jsonと同じ(ペーシング・再試行)。

    Redditのトークン取得のように、検索系(GET)とは別にPOSTが要るプラットフォーム向け。
    """
    return _request_json(
        "POST",
        url,
        data=data,
        headers=headers,
        auth=auth,
        timeout=timeout,
        interval=interval,
        max_attempts=max_attempts,
        label=label,
    )


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float,
    interval: float,
    max_attempts: int,
    label: str,
) -> dict[str, Any]:
    time.sleep(interval)

    for attempt in range(1, max_attempts + 1):
        # requests.request(method, ...) へ一本化しない。get_json/post_jsonの
        # 呼び分けはtest_http.pyがrequests.get/requests.postを個別にパッチする
        # 前提になっており、一本化するとその前提を壊す
        if method == "GET":
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
        else:
            response = requests.post(
                url, params=params, data=data, headers=headers, auth=auth, timeout=timeout
            )

        if response.status_code not in RETRYABLE_STATUS or attempt == max_attempts:
            response.raise_for_status()
            return response.json()

        wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            wait = max(wait, float(retry_after))

        prefix = f"[{label}] " if label else ""
        print(
            f"  {prefix}HTTP {response.status_code} のため {wait:.0f}秒待機して再試行 "
            f"({attempt}/{max_attempts - 1})"
        )
        time.sleep(wait)

    # max_attempts >= 1 である限り到達しない
    raise AssertionError("unreachable")
