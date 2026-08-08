from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ..common.config import HackerNewsConfig
from ..common.storage import append_jsonl
from ..db import connect, insert_records, known_ids, record_keyword_hits
from .client import search_items
from .models import HackerNewsItem

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb


def run(config: HackerNewsConfig, data_dir: Path, db_path: Path) -> None:
    # 重複判定はDBの posts に一本化した（ADR-0004）
    with connect(db_path) as conn:
        _run_with_db(config, data_dir, conn)


def _run_with_db(config: HackerNewsConfig, data_dir: Path, conn: duckdb.DuckDBPyConnection) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    # 起動時に1回だけ引く。1件ずつ問い合わせると、キーワード数×件数のクエリになる
    seen = known_ids(conn, "hackernews")
    run_seen: set[str] = set()
    failed_keywords: list[str] = []
    total_new = 0
    output_path: Path | None = None

    for keyword in config.keywords:
        # 1キーワードの失敗で run 全体を落とさない。
        # 取りこぼしたキーワードは次回の定期実行でカバーされる。
        try:
            hits = search_items(keyword, config.tags, config.hits_per_page)
        except requests.RequestException as e:
            print(f"[hackernews:{keyword}] 取得失敗のためスキップ: {e}")
            failed_keywords.append(keyword)
            continue

        known_hits: list[str] = []
        new_items: list[HackerNewsItem] = []
        skip_count = 0
        malformed_count = 0
        for hit in hits:
            # APIレスポンスの形が想定と違っても、その1件だけを捨てて処理を続ける。
            try:
                item = HackerNewsItem.from_hit(hit, keyword, collected_at)
            except (KeyError, TypeError, ValueError) as e:
                malformed_count += 1
                print(f"  [hackernews:{keyword}] 不正な投稿をスキップ: {e}")
                continue

            if item.item_id in run_seen:
                skip_count += 1
                continue
            if item.item_id in seen:
                # JSONLには書かないが、この語でも見つかった事実はDBへ残す
                known_hits.append(item.item_id)
                skip_count += 1
                continue
            run_seen.add(item.item_id)
            new_items.append(item)

        # キーワード単位で保存する。ここでまとめずrun末尾に持ち越すと、
        # 以降のキーワードで予期しない例外が出た際に収集済みの全件を失う。
        # JSONLを先に書き、成功してからDBへ入れる。逆順にすると
        # 書き込み前にプロセスが落ちた場合、その投稿を二度と収集できなくなる
        # （DBに既知として記録済みなのでスキップされる）。
        if new_items:
            records = [i.to_dict() for i in new_items]
            output_path = append_jsonl(records, data_dir, today)
            result = insert_records(conn, "hackernews", records)
            if result.failed:
                print(
                    f"  [hackernews:{keyword}] {result.failed}件がDBに入らなかった。"
                    "重複判定できず次回も再収集される"
                )
            seen.update(i.item_id for i in new_items)
            total_new += len(new_items)

        record_keyword_hits(conn, "hackernews", known_hits, keyword)

        message = (
            f"[hackernews:{keyword}] 取得: {len(hits)}件 "
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
