"""JSONL 1行を posts の共通形へ正規化する。

プラットフォーム差異はここだけで吸収する。DB側もロード処理も
プラットフォームを知らない。

**過去に書かれたJSONLも読めること。** 収集側のフィールドは後から増える
（author_did / lang / raw は2026-08-02に追加した）。古い行にそれらは無いため、
すべて欠損を許容して読む。欠損を理由に行を捨てると、収集済みデータを失う。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ...domain.post import MappingError, PostRow


def _parse_timestamp(value: Any) -> datetime | None:
    """ISO8601をUTCのnaive datetimeへ。壊れていればNoneにする。

    **必ずUTCへ揃えてからtzinfoを外す。** `posts.posted_at` は naive TIMESTAMP で、
    aware datetime をそのまま渡すとDuckDBがセッションの TimeZone でローカル時刻へ
    変換して格納する。同じJSONLでも実行した機械のTZで値が変わり、
    「JSONLがあれば再構築できる」(F-04) が成立しなくなる。

    日時が読めないことは行を捨てる理由にならない。本文と投稿IDが揃っていれば
    重複排除と抽出には足りる。
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        # オフセットの無い表記はUTCとみなす。ローカルTZで解釈すると
        # 上と同じ「機械によって値が変わる」問題に戻る
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _first_lang(value: Any) -> str | None:
    """Blueskyの langs は配列。先頭だけを採る。"""
    if isinstance(value, list):
        return str(value[0]) if value else None
    if isinstance(value, str) and value:
        return value
    return None


def _required(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise MappingError(f"必須フィールド {key} が無い、または空")
    return value


def from_bluesky(record: dict[str, Any]) -> PostRow:
    native_id = _required(record, "post_id")
    metrics = {
        "like_count": record.get("like_count", 0),
        "repost_count": record.get("repost_count", 0),
        "reply_count": record.get("reply_count", 0),
    }
    keyword = record.get("keyword")

    return PostRow(
        id=f"bluesky:{native_id}",
        platform="bluesky",
        native_id=native_id,
        author_id=record.get("author_did") or None,
        author_handle=record.get("author_handle") or None,
        text=record.get("text", ""),
        url=record.get("url") or None,
        lang=_first_lang(record.get("lang")),
        posted_at=_parse_timestamp(record.get("created_at")),
        collected_at=_parse_timestamp(record.get("collected_at")),
        matched_keywords=[keyword] if isinstance(keyword, str) and keyword else [],
        metrics=json.dumps(metrics, ensure_ascii=False),
        raw=json.dumps(record.get("raw") or record, ensure_ascii=False),
    )


def from_youtube(record: dict[str, Any]) -> PostRow:
    native_id = _required(record, "video_id")
    title = record.get("title", "")
    description = record.get("description", "")
    # 検索できるのはメタデータだけなので、タイトルと説明文を1つの本文として扱う
    text = "\n".join(part for part in (title, description) if part)
    keyword = record.get("keyword")

    return PostRow(
        id=f"youtube:{native_id}",
        platform="youtube",
        native_id=native_id,
        author_id=record.get("channel_id") or None,
        author_handle=record.get("channel_title") or None,
        text=text,
        url=record.get("url") or None,
        # search.list は言語を返さない。videos.list を叩かない限り埋まらない
        lang=None,
        posted_at=_parse_timestamp(record.get("published_at")),
        collected_at=_parse_timestamp(record.get("collected_at")),
        matched_keywords=[keyword] if isinstance(keyword, str) and keyword else [],
        # search.list には再生数・高評価数が含まれない。空で埋める
        metrics=json.dumps({}, ensure_ascii=False),
        raw=json.dumps(record.get("raw") or record, ensure_ascii=False),
    )


def from_hackernews(record: dict[str, Any]) -> PostRow:
    native_id = _required(record, "item_id")
    keyword = record.get("keyword")

    return PostRow(
        id=f"hackernews:{native_id}",
        platform="hackernews",
        native_id=native_id,
        # HNにはハンドルと別の安定IDが無い。ユーザー名自体が変わらない識別子
        author_id=record.get("author") or None,
        author_handle=record.get("author") or None,
        text=record.get("text", ""),
        url=record.get("url") or None,
        # Algolia検索APIは言語を返さない
        lang=None,
        posted_at=_parse_timestamp(record.get("created_at")),
        collected_at=_parse_timestamp(record.get("collected_at")),
        matched_keywords=[keyword] if isinstance(keyword, str) and keyword else [],
        metrics=json.dumps(
            {
                "points": record.get("points", 0),
                "num_comments": record.get("num_comments", 0),
                "item_type": record.get("item_type"),
                "story_id": record.get("story_id"),
            },
            ensure_ascii=False,
        ),
        raw=json.dumps(record.get("raw") or record, ensure_ascii=False),
    )


def from_hnjobs(record: dict[str, Any]) -> PostRow:
    native_id = _required(record, "item_id")
    keyword = record.get("keyword")

    return PostRow(
        id=f"hnjobs:{native_id}",
        platform="hnjobs",
        native_id=native_id,
        # HNにはハンドルと別の安定IDが無い。ユーザー名自体が変わらない識別子
        author_id=record.get("author") or None,
        author_handle=record.get("author") or None,
        text=record.get("text", ""),
        url=record.get("url") or None,
        # Algolia検索APIは言語を返さない
        lang=None,
        posted_at=_parse_timestamp(record.get("created_at")),
        collected_at=_parse_timestamp(record.get("collected_at")),
        matched_keywords=[keyword] if isinstance(keyword, str) and keyword else [],
        # 求人か案件か、発注側か受注側かは分析時の必須の軸。
        # 平坦化で落とさずここへ残す（seekingを落とすと金の流れを読み違える）
        metrics=json.dumps(
            {
                "thread_id": record.get("thread_id"),
                "thread_title": record.get("thread_title"),
                "thread_kind": record.get("thread_kind"),
                "seeking": record.get("seeking"),
            },
            ensure_ascii=False,
        ),
        raw=json.dumps(record.get("raw") or record, ensure_ascii=False),
    )


def from_github(record: dict[str, Any]) -> PostRow:
    native_id = _required(record, "issue_id")
    keyword = record.get("keyword")

    return PostRow(
        id=f"github:{native_id}",
        platform="github",
        native_id=native_id,
        # loginは改名で変わる。ユーザーの数値IDは変わらない(BlueskyのDIDと同じ役割)
        author_id=record.get("author_id") or None,
        author_handle=record.get("author") or None,
        text=record.get("text", ""),
        url=record.get("url") or None,
        # 検索APIは言語を返さない
        lang=None,
        posted_at=_parse_timestamp(record.get("created_at")),
        collected_at=_parse_timestamp(record.get("collected_at")),
        matched_keywords=[keyword] if isinstance(keyword, str) and keyword else [],
        metrics=json.dumps(
            {
                "comments": record.get("comments", 0),
                "reactions": record.get("reactions", 0),
                "state": record.get("state"),
                "repo_full_name": record.get("repo_full_name"),
                "number": record.get("number"),
                "labels": record.get("labels", []),
            },
            ensure_ascii=False,
        ),
        raw=json.dumps(record.get("raw") or record, ensure_ascii=False),
    )


def from_reddit(record: dict[str, Any]) -> PostRow:
    native_id = _required(record, "post_id")
    keyword = record.get("keyword")

    return PostRow(
        id=f"reddit:{native_id}",
        platform="reddit",
        native_id=native_id,
        # author_fullname("t2_xxx")は改名で変わらない。author(表示名)は変わりうる
        author_id=record.get("author_id") or None,
        author_handle=record.get("author") or None,
        text=record.get("text", ""),
        url=record.get("url") or None,
        # 検索APIは言語を返さない
        lang=None,
        # created_utc(epoch)はmodels側でISO8601へ変換済み
        posted_at=_parse_timestamp(record.get("created_at")),
        collected_at=_parse_timestamp(record.get("collected_at")),
        matched_keywords=[keyword] if isinstance(keyword, str) and keyword else [],
        metrics=json.dumps(
            {
                "score": record.get("score", 0),
                "num_comments": record.get("num_comments", 0),
                "upvote_ratio": record.get("upvote_ratio"),
                "subreddit": record.get("subreddit"),
                "link_url": record.get("link_url"),
            },
            ensure_ascii=False,
        ),
        raw=json.dumps(record.get("raw") or record, ensure_ascii=False),
    )


ADAPTERS = {
    "bluesky": from_bluesky,
    "youtube": from_youtube,
    "hackernews": from_hackernews,
    "hnjobs": from_hnjobs,
    "github": from_github,
    "reddit": from_reddit,
}
