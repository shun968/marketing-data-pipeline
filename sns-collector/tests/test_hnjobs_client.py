from __future__ import annotations

from unittest.mock import patch

from sns_collector.adapter.source.hnjobs.client import list_threads, search_thread


def test_hitsがnullでも空配列を返す():
    """`.get("hits", [])`はキーが存在しnullのとき既定値を使わない。

    後続の`for hit in hits:`(search.py)がTypeErrorで落ち、
    requests.RequestExceptionの隔離をすり抜けてrun全体が止まる。
    """
    with patch("sns_collector.adapter.source.hnjobs.client.get_json", return_value={"hits": None}):
        assert search_thread("1", "kw", 50) == []
        assert list_threads("whoishiring", 50) == []


def test_hitsキーが無くても空配列を返す():
    with patch("sns_collector.adapter.source.hnjobs.client.get_json", return_value={}):
        assert search_thread("1", "kw", 50) == []


def test_スレッド内検索はタイプミス吸収を無効にする():
    """Algolia既定のタイプミス吸収は短い語を別語へ広げる。

    "cnc"は2026年8月の求人スレッドで13件ヒットしたが、中身は不動産・請負業者の
    マッチングサービス等で工作機械と無関係だった。無効化すると0件になる。
    件数から領域の厚みを判断するため、ここが効くと結論そのものが歪む。
    """
    with patch(
        "sns_collector.adapter.source.hnjobs.client.get_json", return_value={"hits": []}
    ) as mock_get:
        search_thread("49156683", "cnc", 50)

    assert mock_get.call_args.kwargs["params"]["typoTolerance"] == "false"


def test_スレッド一覧は投稿者タグで引く():
    """タイトルの全文検索では別人の関連スレッドが混ざる(2026-08-11 実測)。"""
    with patch(
        "sns_collector.adapter.source.hnjobs.client.get_json", return_value={"hits": []}
    ) as mock_get:
        list_threads("jon_north", 12)

    params = mock_get.call_args.kwargs["params"]
    assert params["tags"] == "story,author_jon_north"
    assert params["hitsPerPage"] == 12


def test_スレッド内検索はstoryタグでコメントに限定する():
    with patch(
        "sns_collector.adapter.source.hnjobs.client.get_json", return_value={"hits": []}
    ) as mock_get:
        search_thread("49156683", "embedded", 50)

    assert mock_get.call_args.kwargs["params"]["tags"] == "comment,story_49156683"
