"""各収集元のタスク生成。

ここで見るのは「何を検索するか」と「失敗の形」だけ。
生レスポンスの読み方は各 `test_*_models.py` が、収集の手順は
`test_collect.py` が担保する（ADR-0011で役割を分けた）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import ModuleType

import pytest
import requests

from sns_collector.adapter.source.bluesky import source as bluesky_source
from sns_collector.adapter.source.github import source as github_source
from sns_collector.adapter.source.hackernews import source as hackernews_source
from sns_collector.adapter.source.reddit import source as reddit_source
from sns_collector.adapter.source.youtube import source as youtube_source
from sns_collector.domain.collect import SourceUnavailable
from sns_collector.domain.config import (
    BlueskyConfig,
    GitHubConfig,
    HackerNewsConfig,
    RedditConfig,
    YouTubeConfig,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
KEYWORDS = ["語1", "語2"]

# (収集元モジュール, クライアント関数名, 設定, ラベルの接頭辞)
CASES = [
    (
        bluesky_source,
        "search_posts",
        BlueskyConfig(sort="latest", limit_per_keyword=50, keywords=KEYWORDS),
        "bluesky",
    ),
    (
        youtube_source,
        "search_videos",
        YouTubeConfig(
            api_key="dummy",
            order="relevance",
            max_results_per_keyword=25,
            region_code="JP",
            relevance_language="ja",
            keywords=KEYWORDS,
        ),
        "youtube",
    ),
    (
        hackernews_source,
        "search_items",
        HackerNewsConfig(tags="(story,comment)", hits_per_page=50, keywords=KEYWORDS),
        "hackernews",
    ),
    (
        github_source,
        "search_issues",
        GitHubConfig(token=None, qualifiers="is:issue", per_page=50, keywords=KEYWORDS),
        "github",
    ),
]


@pytest.mark.parametrize(("module", "client_attr", "config", "prefix"), CASES)
def test_キーワードごとに1タスクを作る(
    module: ModuleType, client_attr: str, config: object, prefix: str
):
    tasks = module.tasks(config, NOW, lambda _m: None)

    assert [t.keyword for t in tasks] == KEYWORDS
    assert [t.label for t in tasks] == [f"{prefix}:{k}" for k in KEYWORDS]


@pytest.mark.parametrize(("module", "client_attr", "config", "prefix"), CASES)
def test_通信失敗はSourceUnavailableへ変換する(
    module: ModuleType,
    client_attr: str,
    config: object,
    prefix: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """usecase は requests を知らない。この形でしか失敗を受け取れない（ADR-0011）。

    ここが素の RequestException のまま漏れると、収集ユースケースの
    タスク単位の隔離をすり抜けて run 全体が落ちる。
    """

    def boom(*_args, **_kwargs):
        raise requests.HTTPError("503 Server Error")

    monkeypatch.setattr(module, client_attr, boom)
    task = module.tasks(config, NOW, lambda _m: None)[0]

    with pytest.raises(SourceUnavailable):
        task.fetch()


def _reddit_config() -> RedditConfig:
    return RedditConfig(
        client_id="id",
        client_secret="secret",
        user_agent="test:app:1.0 (by /u/test)",
        sort="new",
        time_filter="month",
        limit_per_keyword=50,
        keywords=KEYWORDS,
    )


class _FakeProvider:
    """トークンの保持・期限判定そのものは test_reddit_auth.py が見る。"""

    def __init__(self, *_args, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def token(self) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return "token"


def test_redditはタスクを作る前にトークンを取りに行く(monkeypatch: pytest.MonkeyPatch):
    """検索を始めてから気づくと、失敗が全キーワードに分散して原因が見えにくい。"""
    provider = _FakeProvider()
    monkeypatch.setattr(reddit_source, "TokenProvider", lambda *_a: provider)

    tasks = reddit_source.tasks(_reddit_config(), NOW, lambda _m: None)

    assert len(tasks) == len(KEYWORDS)
    assert provider.calls == 1, "タスク生成の時点で1回だけ確認する"


def test_redditはトークン取得に失敗したら1件も検索しない(monkeypatch: pytest.MonkeyPatch):
    """まだ何も書いていないため、ここで中止しても失われる収集データは無い。"""
    provider = _FakeProvider(error=requests.HTTPError("401 Unauthorized"))
    monkeypatch.setattr(reddit_source, "TokenProvider", lambda *_a: provider)

    with pytest.raises(SourceUnavailable):
        reddit_source.tasks(_reddit_config(), NOW, lambda _m: None)
