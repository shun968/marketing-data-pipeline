from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from sns_collector.common.config import RedditConfig
from sns_collector.reddit import search as reddit_search


def _config(keywords: list[str]) -> RedditConfig:
    return RedditConfig(
        client_id="id",
        client_secret="secret",
        user_agent="test:app:1.0 (by /u/test)",
        sort="new",
        time_filter="month",
        limit_per_keyword=50,
        keywords=keywords,
    )


FAKE_POST = {
    "name": "t3_1abcdef",
    "title": "タイトル",
    "selftext": "本文だよ",
    "subreddit": "maritime",
    "author": "someone",
    "author_fullname": "t2_1234",
    "score": 12,
    "num_comments": 4,
    "upvote_ratio": 0.9,
    "created_utc": 1754611200.0,
    "permalink": "/r/maritime/comments/1abcdef/",
    "url": "https://www.reddit.com/r/maritime/comments/1abcdef/",
}


def _no_op_token_provider():
    """TokenProviderの生成・トークン取得を実HTTP無しで通す。"""
    return patch.object(
        reddit_search, "TokenProvider", return_value=type("P", (), {"token": lambda self: "t"})()
    )


def test_run_writes_new_items_and_skips_duplicates(tmp_path: Path):
    config = _config(["collision avoidance"])
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with (
        _no_op_token_provider(),
        patch("sns_collector.reddit.search.search_posts", return_value=[FAKE_POST]),
    ):
        reddit_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["post_id"] == "t3_1abcdef"

    with (
        _no_op_token_provider(),
        patch("sns_collector.reddit.search.search_posts", return_value=[FAKE_POST]),
    ):
        reddit_search.run(config, data_dir=data_dir, db_path=db_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1


def test_failed_keyword_does_not_discard_other_results(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword, *_args):
        if keyword == "失敗する語":
            raise requests.HTTPError("503 Server Error")
        return [FAKE_POST]

    with (
        _no_op_token_provider(),
        patch("sns_collector.reddit.search.search_posts", side_effect=fake_search),
    ):
        reddit_search.run(_config(["成功する語", "失敗する語"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1
    assert db_path.exists(), "分析DBが作られていない"


def test_unexpected_exception_does_not_discard_saved_results(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword, *_args):
        if keyword == "壊れる語":
            raise RuntimeError("想定外の例外")
        return [FAKE_POST]

    with (
        _no_op_token_provider(),
        patch("sns_collector.reddit.search.search_posts", side_effect=fake_search),
        pytest.raises(RuntimeError),
    ):
        reddit_search.run(_config(["成功する語", "壊れる語"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1, "例外の前に収集した分がディスクに書かれていない"
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_malformed_item_is_skipped_without_losing_others(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    broken_post = {k: v for k, v in FAKE_POST.items() if k != "name"}
    other_post = {**FAKE_POST, "name": "t3_other456"}

    with (
        _no_op_token_provider(),
        patch(
            "sns_collector.reddit.search.search_posts",
            return_value=[broken_post, FAKE_POST, other_post],
        ),
    ):
        reddit_search.run(_config(["キーワード"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 2


def test_トークン取得に失敗したらキーワードを1つも叩かずに終える(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def failing_token(self):
        raise requests.HTTPError("401 Unauthorized")

    with (
        patch.object(
            reddit_search,
            "TokenProvider",
            return_value=type("P", (), {"token": failing_token})(),
        ),
        patch("sns_collector.reddit.search.search_posts") as mock_search,
    ):
        reddit_search.run(_config(["キーワード"]), data_dir=data_dir, db_path=db_path)

    mock_search.assert_not_called()
    assert list(data_dir.glob("*.jsonl")) == []


def test_トークンはキーワードごとに取り直さない(tmp_path: Path):
    """TokenProviderの生成(=資格情報を渡す箇所)はrun 1回につき1回だけ。

    token()自体はキーワードごとに呼ぶが、キャッシュ済みなら通信は発生しない
    (TokenProvider内部の責務であり、search.py側は気にしない)。
    """
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with (
        _no_op_token_provider() as mock_provider_class,
        patch("sns_collector.reddit.search.search_posts", return_value=[]),
    ):
        reddit_search.run(_config(["語1", "語2", "語3"]), data_dir=data_dir, db_path=db_path)

    mock_provider_class.assert_called_once_with("id", "secret", "test:app:1.0 (by /u/test)")


def test_トークン応答が不正でも生のKeyErrorでrunが落ちない(tmp_path: Path):
    """RedditがOAuth失敗をHTTP 200 + エラー本文で返すケース(実TokenProviderを使う)。

    fetch_token内部のKeyErrorがrequests.RequestExceptionへ変換されないと、
    冒頭のトークン先取りのtry/exceptをすり抜けてrunが生のトレースバックで落ちる。
    """
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with (
        patch("sns_collector.reddit.auth.post_json", return_value={"error": "invalid_grant"}),
        patch("sns_collector.reddit.search.search_posts") as mock_search,
    ):
        reddit_search.run(_config(["キーワード"]), data_dir=data_dir, db_path=db_path)

    mock_search.assert_not_called()
    assert list(data_dir.glob("*.jsonl")) == []
