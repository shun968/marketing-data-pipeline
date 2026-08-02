from __future__ import annotations

import json

import pytest

from sns_collector.db.adapters import AdapterError, from_bluesky, from_youtube
from tests.conftest import BLUESKY_RECORD, YOUTUBE_RECORD


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


def test_必須フィールドが無ければ弾く():
    broken = {k: v for k, v in BLUESKY_RECORD.items() if k != "post_id"}
    with pytest.raises(AdapterError):
        from_bluesky(broken)

    with pytest.raises(AdapterError):
        from_youtube({**YOUTUBE_RECORD, "video_id": ""})


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
