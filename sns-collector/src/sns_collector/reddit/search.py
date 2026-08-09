from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ..common.config import RedditConfig
from ..common.storage import append_jsonl
from ..db import connect, insert_records, known_ids, record_keyword_hits
from .auth import TokenProvider
from .client import search_posts
from .models import RedditPost

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb


def run(config: RedditConfig, data_dir: Path, db_path: Path) -> None:
    # 重複判定はDBの posts に一本化した(ADR-0004)
    with connect(db_path) as conn:
        _run_with_db(config, data_dir, conn)


def _run_with_db(config: RedditConfig, data_dir: Path, conn: duckdb.DuckDBPyConnection) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    seen = known_ids(conn, "reddit")
    run_seen: set[str] = set()
    failed_keywords: list[str] = []
    total_new = 0
    output_path: Path | None = None

    provider = TokenProvider(config.client_id, config.client_secret, config.user_agent)

    # トークンを先に1回取る。ここで失敗したら1キーワードも叩かずに終える。
    # まだ何も書いていないため、失われる収集データは無い
    try:
        provider.token()
    except requests.RequestException as e:
        print(f"[reddit] アクセストークンを取得できないため収集を中止: {e}")
        print("  REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET を確認すること。")
        return

    for keyword in config.keywords:
        try:
            hits = search_posts(
                keyword,
                provider.token(),
                config.user_agent,
                config.limit_per_keyword,
                config.sort,
                config.time_filter,
            )
        except requests.RequestException as e:
            print(f"[reddit:{keyword}] 取得失敗のためスキップ: {e}")
            failed_keywords.append(keyword)
            continue

        known_hits: list[str] = []
        new_items: list[RedditPost] = []
        skip_count = 0
        malformed_count = 0
        for hit in hits:
            try:
                item = RedditPost.from_post(hit, keyword, collected_at)
            except (KeyError, TypeError, ValueError) as e:
                malformed_count += 1
                print(f"  [reddit:{keyword}] 不正な投稿をスキップ: {e}")
                continue

            if item.post_id in run_seen:
                skip_count += 1
                continue
            if item.post_id in seen:
                known_hits.append(item.post_id)
                skip_count += 1
                continue
            run_seen.add(item.post_id)
            new_items.append(item)

        if new_items:
            records = [i.to_dict() for i in new_items]
            output_path = append_jsonl(records, data_dir, today)
            result = insert_records(conn, "reddit", records)
            if result.failed:
                print(
                    f"  [reddit:{keyword}] {result.failed}件がDBに入らなかった。"
                    "重複判定できず次回も再収集される"
                )
            seen.update(i.post_id for i in new_items)
            total_new += len(new_items)

        record_keyword_hits(conn, "reddit", known_hits, keyword)

        message = (
            f"[reddit:{keyword}] 取得: {len(hits)}件 "
            f"/ 新規: {len(new_items)}件 / スキップ: {skip_count}件"
        )
        if malformed_count:
            message += f" / 不正: {malformed_count}件"
        print(message)

    if output_path is None:
        print(f"新規の投稿はありませんでした。(収集先: {data_dir})")
    else:
        print(f"合計 {total_new} 件を {output_path} に保存しました。")

    if failed_keywords:
        print(
            f"取得に失敗したキーワード {len(failed_keywords)}/{len(config.keywords)} 件: "
            f"{', '.join(failed_keywords)}"
        )
