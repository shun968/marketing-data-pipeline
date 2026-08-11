from __future__ import annotations

from unittest.mock import patch

from sns_collector.adapter.source.reddit.client import search_posts


def _search(payload: dict) -> list[dict]:
    with patch("sns_collector.adapter.source.reddit.client.get_json", return_value=payload):
        return search_posts("kw", "token", "test-agent", 50, "new", "month")


def test_dataがnullでも空配列を返す():
    """Redditは"data"キー自体をnullで返すことがある。

    `.get("data", {})`はキーが存在しnullのとき既定値を使わないため、後続の
    `.get("children", [])`呼び出しがAttributeErrorで落ちる。search.pyの
    requests.RequestException隔離をすり抜けてrunが落ちる原因になっていた。
    """
    assert _search({"data": None}) == []


def test_childrenがnullでも空配列を返す():
    assert _search({"data": {"children": None}}) == []


def test_通常のレスポンスは投稿データへ展開する():
    payload = {"data": {"children": [{"kind": "t3", "data": {"name": "t3_1"}}]}}
    assert _search(payload) == [{"name": "t3_1"}]
