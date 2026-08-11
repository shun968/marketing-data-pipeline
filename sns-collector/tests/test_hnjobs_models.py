from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sns_collector.adapter.source.hnjobs.dto import (
    HackerNewsJobPost,
    is_job_entry,
    seeking_role,
    thread_authors,
    thread_kind,
)

THREAD = {"objectID": "49156683", "title": "Ask HN: Who is hiring? (August 2026)"}

TOP_LEVEL_HIT = {
    "objectID": "49175131",
    "author": "bzimm",
    "created_at": "2026-08-05T12:00:00Z",
    "parent_id": 49156683,
    "story_id": 49156683,
    "comment_text": (
        "Brightcore Energy | Senior Embedded Engineer | Brooklyn, NY"
        "<p>$140k-$170k&#x2F;year, hybrid."
    ),
}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Ask HN: Who is hiring? (August 2026)", "hiring"),
        ("Ask HN: Freelancer? Seeking freelancer? (August 2026)", "freelancer"),
        ("Ask HN: Who wants to be hired? (August 2026)", "hired"),
        # 大小文字の違いで取りこぼさない
        ("ASK HN: WHO IS HIRING? (AUGUST 2026)", "hiring"),
    ],
)
def test_thread_kind_classifies_monthly_threads(title: str, expected: str):
    assert thread_kind(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        # whoishiringは月次スレッド以外も立てうる。既知の3種以外は採らない
        "Ask HN: Why is the post being re-aged?",
        "",
    ],
)
def test_thread_kind_returns_none_for_unknown_titles(title: str):
    """既知の3種以外をNoneにできないと、種別不明のスレッドを求人として集める。

    タイトルに "hiring" を含む他人のスレッド（Show HN: HN Hiring 等）の排除は
    ここではなく client.py の author_whoishiring が担う。責務を分けてある。
    """
    assert thread_kind(title) is None


def test_thread_authors_covers_every_selected_kind():
    """案件スレッドの主催は求人スレッドと別。片方だけ引くと案件が0件になる。"""
    assert thread_authors(["hiring"]) == ["whoishiring"]
    assert thread_authors(["freelancer"]) == ["whoishiring", "jon_north"]


def test_thread_authors_does_not_repeat_shared_hosts():
    """同じアカウントを2回引くと、同一スレッドを二重に処理して無駄な通信になる。"""
    authors = thread_authors(["hiring", "freelancer", "hired"])
    assert authors == ["whoishiring", "jon_north"]


def test_is_job_entry_accepts_top_level_comment():
    assert is_job_entry(TOP_LEVEL_HIT) is True


def test_is_job_entry_rejects_reply():
    """返信は求人票ではなく議論。採ると「Incorrect.」のような断片がDBへ入る。"""
    reply = {**TOP_LEVEL_HIT, "parent_id": 49175131, "story_id": 49156683}
    assert is_job_entry(reply) is False


def test_is_job_entry_rejects_hit_without_parent():
    """parent_idが欠けた応答をトップレベル扱いしない(欠損同士の一致で通さない)。"""
    assert is_job_entry({"objectID": "1", "story_id": None}) is False


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("SEEKING WORK | Remote | Location: Los Angeles, CA", "work"),
        ("SEEKING FREELANCER | Berlin | Rust, embedded", "freelancer"),
        ("Seeking Freelancer | 小文字混じりでも拾う", "freelancer"),
        # 名乗りが無い投稿もある（実測: 案件スレッドの5件中1件）
        ("I'm a seasoned generalist with deep focus in game development", None),
        ("", None),
    ],
)
def test_seeking_role_separates_buyer_from_seller(body: str, expected: str | None):
    """発注側と受注側を混ぜると金の流れを読み違える。

    2026年8月の案件スレッドはトップレベル14件すべてがSEEKING WORK（受注側）で、
    発注側は0件だった。区別せず数えると「案件が14件ある」と誤読する。
    """
    assert seeking_role(body) == expected


def test_seeking_role_ignores_marker_far_into_the_body():
    """名乗りは冒頭に置かれる。経歴中の同じ語を拾うと判定が壊れる。"""
    body = "Full-stack engineer. " + "x" * 200 + " seeking work with startups"
    assert seeking_role(body) is None


def test_from_hit_records_seeking_role():
    hit = {**TOP_LEVEL_HIT, "comment_text": "SEEKING FREELANCER | Remote | embedded"}
    item = HackerNewsJobPost.from_hit(
        hit, "embedded", THREAD, "freelancer", datetime(2026, 8, 11, tzinfo=UTC)
    )
    assert item.seeking == "freelancer"


def test_from_hit_builds_record_with_thread_context():
    item = HackerNewsJobPost.from_hit(
        TOP_LEVEL_HIT, "embedded", THREAD, "hiring", datetime(2026, 8, 11, tzinfo=UTC)
    )

    assert item.item_id == "49175131"
    assert item.thread_id == "49156683"
    assert item.thread_kind == "hiring"
    assert item.keyword == "embedded"
    assert item.url == "https://news.ycombinator.com/item?id=49175131"
    # 単体では何のスレッドの求人か分からないため、スレッド名が本文の先頭に付く
    assert item.text.startswith("Ask HN: Who is hiring? (August 2026)")
    # HTMLタグとエンティティが残ると要約・判定のノイズになる
    assert "<p>" not in item.text
    assert "$140k-$170k/year" in item.text


def test_from_hit_requires_object_id():
    """必須フィールドを欠く応答は、その1件だけを捨てられるよう例外にする。"""
    broken = {k: v for k, v in TOP_LEVEL_HIT.items() if k != "objectID"}
    with pytest.raises(KeyError):
        HackerNewsJobPost.from_hit(
            broken, "embedded", THREAD, "hiring", datetime(2026, 8, 11, tzinfo=UTC)
        )
