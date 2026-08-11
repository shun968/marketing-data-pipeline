from __future__ import annotations

import json

import pytest

from sns_collector.adapter.db.mapping import (
    MappingError,
    from_bluesky,
    from_github,
    from_hackernews,
    from_hnjobs,
    from_reddit,
    from_youtube,
)
from tests.conftest import (
    BLUESKY_RECORD,
    GITHUB_RECORD,
    HACKERNEWS_RECORD,
    HNJOBS_RECORD,
    REDDIT_RECORD,
    YOUTUBE_RECORD,
)


def test_blueskyのidはプラットフォーム接頭辞を持つ():
    row = from_bluesky(BLUESKY_RECORD)
    assert row.id == "bluesky:at://did:plc:abc/app.bsky.feed.post/xyz"
    assert row.platform == "bluesky"
    assert row.native_id == BLUESKY_RECORD["post_id"]


def test_blueskyのDIDと言語を取り込む():
    row = from_bluesky(BLUESKY_RECORD)
    assert row.author_id == "did:plc:abc"
    assert row.lang == "ja", "langsは配列。先頭を採る"
    assert json.loads(row.metrics)["like_count"] == 3


def test_youtubeはタイトルと説明文を本文として結合する():
    row = from_youtube(YOUTUBE_RECORD)
    assert row.text == "タイトル\n説明文"
    assert row.author_id == "UC123"
    assert row.lang is None, "search.listは言語を返さない"


def test_説明文が空でも本文に余分な改行を残さない():
    row = from_youtube({**YOUTUBE_RECORD, "description": ""})
    assert row.text == "タイトル"


def test_古いJSONLに無いフィールドがあっても読める():
    """author_did / lang / raw は2026-08-02に追加した。

    それ以前のJSONLにこれらは無い。欠損を理由に行を捨てると収集済みデータを失う。
    """
    old = {k: v for k, v in BLUESKY_RECORD.items() if k not in ("author_did", "lang", "raw")}
    row = from_bluesky(old)

    assert row.author_id is None
    assert row.lang is None
    assert json.loads(row.raw)["post_id"] == old["post_id"], "rawが無ければレコード自体を残す"


def test_hackernewsのidはプラットフォーム接頭辞を持つ():
    row = from_hackernews(HACKERNEWS_RECORD)
    assert row.id == "hackernews:49217777"
    assert row.platform == "hackernews"
    assert row.native_id == HACKERNEWS_RECORD["item_id"]


def test_hackernewsは著者名を安定IDとハンドルの両方に使う():
    """HNにはハンドルと別の安定IDが無い。ユーザー名自体が変わらない識別子。"""
    row = from_hackernews(HACKERNEWS_RECORD)
    assert row.author_id == "someone"
    assert row.author_handle == "someone"
    assert row.lang is None, "Algolia検索APIは言語を返さない"


def test_hackernewsのmetricsにitem_typeとstory_idを含める():
    row = from_hackernews(HACKERNEWS_RECORD)
    metrics = json.loads(row.metrics)
    assert metrics == {
        "points": 3,
        "num_comments": 0,
        "item_type": "comment",
        "story_id": "49216362",
    }


def test_hnjobsのidはプラットフォーム接頭辞を持つ():
    row = from_hnjobs(HNJOBS_RECORD)
    assert row.id == "hnjobs:49175131"
    assert row.platform == "hnjobs"
    assert row.native_id == HNJOBS_RECORD["item_id"]


def test_hnjobsのmetricsにスレッド種別と発注受注の別を含める():
    """求人か案件か・発注側か受注側かは分析時の必須の軸。

    平坦化でここを落とすと後から復元できず、受注者の売り込みを
    「案件がある」と数える読み違えが起きる。
    """
    row = from_hnjobs({**HNJOBS_RECORD, "seeking": "work"})
    assert json.loads(row.metrics)["seeking"] == "work"

    row = from_hnjobs(HNJOBS_RECORD)
    metrics = json.loads(row.metrics)
    assert metrics["seeking"] is None
    assert metrics["thread_kind"] == "hiring"
    assert metrics["thread_id"] == "49156683"
    assert metrics["thread_title"] == "Ask HN: Who is hiring? (August 2026)"


def test_hnjobsはitem_idを欠く行を捨てる():
    broken = {k: v for k, v in HNJOBS_RECORD.items() if k != "item_id"}
    with pytest.raises(MappingError):
        from_hnjobs(broken)


def test_githubのidはプラットフォーム接頭辞を持つ():
    row = from_github(GITHUB_RECORD)
    assert row.id == "github:2345678901"
    assert row.platform == "github"
    assert row.native_id == GITHUB_RECORD["issue_id"]


def test_githubはmetricsにlabelsとstateを持つ():
    row = from_github(GITHUB_RECORD)
    metrics = json.loads(row.metrics)
    assert metrics["labels"] == ["bug", "help wanted"]
    assert metrics["state"] == "open"
    assert metrics["repo_full_name"] == "owner/repo"


def test_githubのauthor_idは数値IDでhandleはlogin():
    """loginは改名で変わる。数値IDは変わらない識別子として分ける。"""
    row = from_github(GITHUB_RECORD)
    assert row.author_id == "9999"
    assert row.author_handle == "someone"
    assert row.lang is None, "検索APIは言語を返さない"


def test_redditのidはfullnameを含む():
    row = from_reddit(REDDIT_RECORD)
    assert row.id == "reddit:t3_1abcdef"
    assert row.platform == "reddit"
    assert row.native_id == REDDIT_RECORD["post_id"]


def test_redditのmetricsにscoreとsubredditを持つ():
    row = from_reddit(REDDIT_RECORD)
    metrics = json.loads(row.metrics)
    assert metrics["score"] == 12
    assert metrics["subreddit"] == "maritime"
    assert metrics["upvote_ratio"] == 0.9


def test_redditのauthor_idはfullnameでauthor_handleは表示名():
    row = from_reddit(REDDIT_RECORD)
    assert row.author_id == "t2_1234"
    assert row.author_handle == "someone"


def test_redditのposted_atはmodelsが変換済みのISO8601から読める():
    row = from_reddit(REDDIT_RECORD)
    assert row.posted_at is not None
    assert row.posted_at.isoformat() == "2025-08-08T00:33:37"


def test_必須フィールドが無ければ弾く():
    broken = {k: v for k, v in BLUESKY_RECORD.items() if k != "post_id"}
    with pytest.raises(MappingError):
        from_bluesky(broken)

    with pytest.raises(MappingError):
        from_youtube({**YOUTUBE_RECORD, "video_id": ""})

    with pytest.raises(MappingError):
        from_hackernews({**HACKERNEWS_RECORD, "item_id": ""})

    with pytest.raises(MappingError):
        from_github({**GITHUB_RECORD, "issue_id": ""})

    with pytest.raises(MappingError):
        from_reddit({**REDDIT_RECORD, "post_id": ""})


def test_日時が壊れていても行は捨てない():
    """日時が読めないことは行を捨てる理由にならない。

    IDと本文が揃っていれば重複排除と抽出には足りる。
    """
    row = from_bluesky({**BLUESKY_RECORD, "created_at": "壊れた日時"})
    assert row.posted_at is None
    assert row.id.startswith("bluesky:")


def test_キーワードが無ければ空配列にする():
    row = from_bluesky({k: v for k, v in BLUESKY_RECORD.items() if k != "keyword"})
    assert row.matched_keywords == []


def test_日時はUTCへ揃えてから格納する():
    """awareなdatetimeをそのまま渡すと、DuckDBがセッションTZでローカル時刻へ変換する。

    同じJSONLでも実行した機械のTZで値が変わり、F-04（JSONLからの再構築）が崩れる。
    """
    row = from_bluesky({**BLUESKY_RECORD, "created_at": "2026-06-05T11:47:05+09:00"})

    assert row.posted_at is not None
    assert row.posted_at.tzinfo is None, "naiveでなければDuckDBがTZ変換してしまう"
    assert row.posted_at.isoformat() == "2026-06-05T02:47:05", "UTCへ揃っていない"


def test_オフセットが無い表記はUTCとみなす():
    row = from_bluesky({**BLUESKY_RECORD, "created_at": "2026-06-05T11:47:05"})
    assert row.posted_at is not None
    assert row.posted_at.isoformat() == "2026-06-05T11:47:05"
