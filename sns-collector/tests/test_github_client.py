from __future__ import annotations

from unittest.mock import patch

from sns_collector.github.client import search_issues


def _search(payload: dict) -> list[dict]:
    with patch("sns_collector.github.client.get_json", return_value=payload):
        return search_issues("kw", "is:issue", 50, None)


def test_itemsがnullでも空配列を返す():
    """GitHubの検索APIは(実測は無いが)"items"キー自体がnullで返る余地がある。

    `.get("items", [])`はキーが存在しnullのとき既定値を使わないため、後続の
    `for hit in hits:`(search.py)がTypeErrorで落ちる。requests.RequestException
    隔離をすり抜けてrunが落ちる原因になっていた。
    """
    assert _search({"items": None}) == []


def test_itemsキーが無くても空配列を返す():
    assert _search({}) == []


def test_通常のレスポンスはissueの配列を返す():
    payload = {"items": [{"id": 1}]}
    assert _search(payload) == [{"id": 1}]
