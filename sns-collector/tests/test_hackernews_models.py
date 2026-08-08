from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sns_collector.hackernews.models import HackerNewsItem

COLLECTED_AT = datetime(2026, 8, 8, tzinfo=UTC)


def test_ストーリーは自分のtitleとurlを持つ():
    hit = {
        "objectID": "1",
        "_tags": ["story"],
        "title": "Show HN: 何か",
        "url": "https://example.com/",
        "story_text": None,
    }
    item = HackerNewsItem.from_hit(hit, "kw", COLLECTED_AT)

    assert item.item_type == "story"
    assert item.title == "Show HN: 何か"
    assert item.url == "https://example.com/"
    assert item.text == "Show HN: 何か"


def test_urlの無いストーリーはHN上のURLへ落ちる():
    """Ask HN等、外部リンクを持たない自己投稿。"""
    hit = {"objectID": "1", "_tags": ["story"], "title": "Ask HN: 何か", "story_text": "本文"}
    item = HackerNewsItem.from_hit(hit, "kw", COLLECTED_AT)

    assert item.url == "https://news.ycombinator.com/item?id=1"
    assert item.text == "Ask HN: 何か\n本文"


def test_コメントは自分のtitleを持たず親ストーリーのタイトルをtextへ含める():
    """コメント単体では何の話か分からないため、story_titleを文脈として使う。"""
    hit = {
        "objectID": "2",
        "_tags": ["comment"],
        "story_title": "元記事のタイトル",
        "comment_text": "本文",
    }
    item = HackerNewsItem.from_hit(hit, "kw", COLLECTED_AT)

    assert item.item_type == "comment"
    assert item.title is None, "コメント自体のtitleは無い"
    assert item.text == "元記事のタイトル\n本文"
    assert item.url == "https://news.ycombinator.com/item?id=2"


def test_HTMLタグとエンティティを除去する():
    hit = {
        "objectID": "3",
        "_tags": ["comment"],
        "comment_text": "&gt; 引用<p>本文だ&#x27;よ&#x27;",
    }
    item = HackerNewsItem.from_hit(hit, "kw", COLLECTED_AT)

    assert item.text == "> 引用本文だ'よ'"


def test_必須フィールドが無ければ例外():
    with pytest.raises(KeyError):
        HackerNewsItem.from_hit({"_tags": ["story"]}, "kw", COLLECTED_AT)
