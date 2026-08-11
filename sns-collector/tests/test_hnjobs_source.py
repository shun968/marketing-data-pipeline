"""hnjobs のタスク生成。

「何を検索するか」を決める部分だけをここで見る。収集そのものの手順
（失敗隔離・冪等性）は収集元によらず `test_collect.py` が担保する。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import requests

from sns_collector.adapter.source.hnjobs import source as hnjobs_source
from sns_collector.domain.collect import SourceUnavailable
from sns_collector.domain.config import ConfigError, HackerNewsJobsConfig

NOW = datetime(2026, 8, 11, tzinfo=UTC)

HIRING_THREAD = {"objectID": "49156683", "title": "Ask HN: Who is hiring? (August 2026)"}
HIRED_THREAD = {"objectID": "49156682", "title": "Ask HN: Who wants to be hired? (August 2026)"}
# 案件スレッドは2026年1月からjon_northが引き継いでいる(2026-08-11 実測)
FREELANCER_THREAD = {
    "objectID": "49157021",
    "title": "Ask HN: Freelancer? Seeking freelancer? (August 2026)",
}
OLD_HIRING_THREAD = {"objectID": "48747976", "title": "Ask HN: Who is hiring? (July 2026)"}

THREADS_BY_AUTHOR = {
    "whoishiring": [HIRING_THREAD, HIRED_THREAD, OLD_HIRING_THREAD],
    "jon_north": [FREELANCER_THREAD],
}

TOP_LEVEL_HIT = {
    "objectID": "49175131",
    "author": "bzimm",
    "created_at": "2026-08-05T12:00:00Z",
    "parent_id": 49156683,
    "story_id": 49156683,
    "comment_text": "Brightcore Energy | Senior Embedded Engineer | Brooklyn, NY",
}


def _use_threads(monkeypatch: pytest.MonkeyPatch, threads_by_author: dict) -> None:
    monkeypatch.setattr(
        hnjobs_source, "list_threads", lambda author, _n: threads_by_author.get(author, [])
    )


def _config(
    keywords: list[str] | None = None,
    thread_kinds: list[str] | None = None,
    thread_limit: int = 4,
) -> HackerNewsJobsConfig:
    return HackerNewsJobsConfig(
        thread_kinds=thread_kinds if thread_kinds is not None else ["hiring", "freelancer"],
        thread_limit=thread_limit,
        hits_per_page=50,
        keywords=keywords or ["embedded"],
    )


def _labels(config: HackerNewsJobsConfig) -> list[str]:
    return [t.label for t in hnjobs_source.tasks(config, NOW, lambda _m: None)]


def test_案件スレッドの主催が別アカウントでも取りこぼさない(monkeypatch: pytest.MonkeyPatch):
    """2026年1月に whoishiring -> jon_north の引き継ぎが起きている。

    単一アカウント固定の実装だと、この月から案件側だけが静かに0件になる。
    """
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    assert any(FREELANCER_THREAD["title"] in label for label in _labels(_config()))


def test_求職スレッドは既定で採らない(monkeypatch: pytest.MonkeyPatch):
    """hired は「金を出す側」ではない。"""
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    assert not any(HIRED_THREAD["title"] in label for label in _labels(_config()))


def test_上限は種別ごとに数える(monkeypatch: pytest.MonkeyPatch):
    """全体で数えると、毎月立つ求人スレッドだけで枠が埋まり案件が溢れる。"""
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    labels = _labels(_config(thread_limit=1))

    assert len(labels) == 2
    assert any(HIRING_THREAD["title"] in label for label in labels)
    assert any(FREELANCER_THREAD["title"] in label for label in labels)
    assert not any(OLD_HIRING_THREAD["title"] in label for label in labels)


def test_スレッドとキーワードの直積になる(monkeypatch: pytest.MonkeyPatch):
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    labels = _labels(_config(keywords=["a", "b"], thread_kinds=["hiring"], thread_limit=1))
    assert len(labels) == 2


def test_未知の種別は収集前に落とす(monkeypatch: pytest.MonkeyPatch):
    """綴り違いを「対象0件」として静かに通すと、収集できていないことに気づけない。"""
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    with pytest.raises(ConfigError, match="hirring"):
        _labels(_config(thread_kinds=["hirring"]))


def test_種別が空なら落とす(monkeypatch: pytest.MonkeyPatch):
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    with pytest.raises(ConfigError):
        _labels(_config(thread_kinds=[]))


def test_objectIDを欠くスレッドは飛ばして残りを使う(monkeypatch: pytest.MonkeyPatch):
    _use_threads(
        monkeypatch,
        {"whoishiring": [{"title": "Ask HN: Who is hiring? (July 2026)"}, HIRING_THREAD]},
    )
    assert len(_labels(_config(thread_kinds=["hiring"]))) == 1


def test_対象スレッドが無ければ空を返して知らせる(monkeypatch: pytest.MonkeyPatch):
    _use_threads(monkeypatch, {})
    messages: list[str] = []

    tasks = hnjobs_source.tasks(_config(), NOW, messages.append)

    assert tasks == []
    assert any("対象スレッドが見つかりません" in m for m in messages)


def test_種別ごとに0件なら警告する(monkeypatch: pytest.MonkeyPatch):
    """主催アカウントの引き継ぎが起きると、その種別だけが静かに0件になる。"""
    _use_threads(monkeypatch, {"whoishiring": THREADS_BY_AUTHOR["whoishiring"]})
    messages: list[str] = []

    hnjobs_source.tasks(_config(), NOW, messages.append)

    assert any("種別 freelancer のスレッドが1件も" in m for m in messages)


def test_返信は求人票として読まない(monkeypatch: pytest.MonkeyPatch):
    """スレッド直下でないコメントは議論。parse が None を返して収集対象から外れる。"""
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    task = hnjobs_source.tasks(
        _config(thread_kinds=["hiring"], thread_limit=1), NOW, lambda _m: None
    )[0]

    reply = {**TOP_LEVEL_HIT, "objectID": "49175999", "parent_id": 49175131}
    assert task.parse(reply) is None
    assert task.parse(TOP_LEVEL_HIT).native_id == "49175131"


def test_通信失敗はSourceUnavailableへ変換する(monkeypatch: pytest.MonkeyPatch):
    """usecase は requests を知らない。この形でしか失敗を受け取れない。"""
    _use_threads(monkeypatch, THREADS_BY_AUTHOR)
    task = hnjobs_source.tasks(
        _config(thread_kinds=["hiring"], thread_limit=1), NOW, lambda _m: None
    )[0]

    def boom(*_args):
        raise requests.HTTPError("503 Server Error")

    monkeypatch.setattr(hnjobs_source, "search_thread", boom)

    with pytest.raises(SourceUnavailable):
        task.fetch()


def test_スレッド一覧の取得失敗もSourceUnavailableになる(monkeypatch: pytest.MonkeyPatch):
    def boom(*_args):
        raise requests.HTTPError("503 Server Error")

    monkeypatch.setattr(hnjobs_source, "list_threads", boom)

    with pytest.raises(SourceUnavailable):
        hnjobs_source.tasks(_config(), NOW, lambda _m: None)
