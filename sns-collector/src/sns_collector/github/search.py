from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ..common.config import GitHubConfig
from ..common.storage import append_jsonl
from ..db import connect, insert_records, known_ids, record_keyword_hits
from .client import search_issues
from .models import GitHubIssue

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb


def run(config: GitHubConfig, data_dir: Path, db_path: Path) -> None:
    # 重複判定はDBの posts に一本化した(ADR-0004)
    with connect(db_path) as conn:
        _run_with_db(config, data_dir, conn)


def _run_with_db(config: GitHubConfig, data_dir: Path, conn: duckdb.DuckDBPyConnection) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    seen = known_ids(conn, "github")
    run_seen: set[str] = set()
    failed_keywords: list[str] = []
    total_new = 0
    output_path: Path | None = None

    for keyword in config.keywords:
        try:
            hits = search_issues(keyword, config.qualifiers, config.per_page, config.token)
        except requests.RequestException as e:
            print(f"[github:{keyword}] 取得失敗のためスキップ: {e}")
            failed_keywords.append(keyword)
            continue

        known_hits: list[str] = []
        new_items: list[GitHubIssue] = []
        skip_count = 0
        malformed_count = 0
        for hit in hits:
            try:
                item = GitHubIssue.from_issue(hit, keyword, collected_at)
            except (KeyError, TypeError, ValueError) as e:
                malformed_count += 1
                print(f"  [github:{keyword}] 不正な投稿をスキップ: {e}")
                continue

            if item.issue_id in run_seen:
                skip_count += 1
                continue
            if item.issue_id in seen:
                known_hits.append(item.issue_id)
                skip_count += 1
                continue
            run_seen.add(item.issue_id)
            new_items.append(item)

        if new_items:
            records = [i.to_dict() for i in new_items]
            output_path = append_jsonl(records, data_dir, today)
            result = insert_records(conn, "github", records)
            if result.failed:
                print(
                    f"  [github:{keyword}] {result.failed}件がDBに入らなかった。"
                    "重複判定できず次回も再収集される"
                )
            seen.update(i.issue_id for i in new_items)
            total_new += len(new_items)

        record_keyword_hits(conn, "github", known_hits, keyword)

        message = (
            f"[github:{keyword}] 取得: {len(hits)}件 "
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
