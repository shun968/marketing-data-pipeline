from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from sns_collector.adapter import http


def _response(status_code: int, payload: dict | None = None, headers: dict | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = payload or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    else:
        response.raise_for_status.return_value = None
    return response


def test_returns_payload_on_success():
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch(
            "sns_collector.adapter.http.requests.get",
            return_value=_response(200, {"posts": [1, 2]}),
        ),
    ):
        assert http.get_json("https://example.test", {}) == {"posts": [1, 2]}


def test_retries_on_403_then_succeeds():
    """Blueskyは連続アクセス時のスロットリングを403で返すため、再試行対象とする。"""
    responses = [_response(403), _response(403), _response(200, {"posts": [1]})]
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch("sns_collector.adapter.http.requests.get", side_effect=responses) as mock_get,
    ):
        assert http.get_json("https://example.test", {}) == {"posts": [1]}
    assert mock_get.call_count == 3


def test_raises_after_max_attempts():
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch(
            "sns_collector.adapter.http.requests.get", side_effect=lambda *a, **kw: _response(429)
        ) as mock_get,
        pytest.raises(requests.HTTPError),
    ):
        http.get_json("https://example.test", {}, max_attempts=3)
    assert mock_get.call_count == 3


def test_does_not_retry_non_retryable_status():
    """404などは再試行しても回復しないため、即座に送出する。"""
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch("sns_collector.adapter.http.requests.get", return_value=_response(404)) as mock_get,
        pytest.raises(requests.HTTPError),
    ):
        http.get_json("https://example.test", {})
    assert mock_get.call_count == 1


def test_respects_retry_after_header():
    responses = [_response(429, headers={"Retry-After": "30"}), _response(200)]
    with (
        patch("sns_collector.adapter.http.time.sleep") as mock_sleep,
        patch("sns_collector.adapter.http.requests.get", side_effect=responses),
    ):
        http.get_json("https://example.test", {}, interval=1.0)

    # 1回目: ペーシングのinterval / 2回目: Retry-After(30秒) がバックオフ既定値を上回る
    assert [c.args[0] for c in mock_sleep.call_args_list] == [1.0, 30.0]


def test_headersをrequests_getへ転送する():
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch("sns_collector.adapter.http.requests.get", return_value=_response(200)) as mock_get,
    ):
        http.get_json("https://example.test", {}, headers={"Authorization": "Bearer x"})
    assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer x"}


def test_headers未指定でも既存の呼び出し形が壊れない():
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch("sns_collector.adapter.http.requests.get", return_value=_response(200)) as mock_get,
    ):
        http.get_json("https://example.test", {})
    assert mock_get.call_args.kwargs["headers"] is None


def test_post_jsonはdataとauthとheadersを渡す():
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch(
            "sns_collector.adapter.http.requests.post", return_value=_response(200, {"ok": True})
        ) as mock_post,
    ):
        result = http.post_json(
            "https://example.test/token",
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": "test-agent"},
            auth=("id", "secret"),
        )
    assert result == {"ok": True}
    assert mock_post.call_args.kwargs["data"] == {"grant_type": "client_credentials"}
    assert mock_post.call_args.kwargs["headers"] == {"User-Agent": "test-agent"}
    assert mock_post.call_args.kwargs["auth"] == ("id", "secret")


def test_post_jsonも429で再試行する():
    responses = [_response(429), _response(200, {"access_token": "t"})]
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch("sns_collector.adapter.http.requests.post", side_effect=responses) as mock_post,
    ):
        assert http.post_json("https://example.test/token") == {"access_token": "t"}
    assert mock_post.call_count == 2


def test_post_jsonは再試行対象外のステータスで即座に送出する():
    """資格情報の誤り(401)が延々リトライされないことの回帰。"""
    with (
        patch("sns_collector.adapter.http.time.sleep"),
        patch("sns_collector.adapter.http.requests.post", return_value=_response(401)) as mock_post,
        pytest.raises(requests.HTTPError),
    ):
        http.post_json("https://example.test/token")
    assert mock_post.call_count == 1
