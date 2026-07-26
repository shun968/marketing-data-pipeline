from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..common.config import BlueskyConfig
from ..common.seen_store import SeenStore
from ..common.storage import append_jsonl
from .client import search_posts
from .models import BlueskyPost


def run(config: BlueskyConfig, data_dir: Path, state_path: Path) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    seen_store = SeenStore(state_path, today=today)
    run_seen: set[str] = set()
    new_posts: list[BlueskyPost] = []

    for keyword in config.keywords:
        raw_posts = search_posts(keyword, config.sort, config.limit_per_keyword)
        new_count = 0
        skip_count = 0
        for raw_post in raw_posts:
            post = BlueskyPost.from_post(raw_post, keyword, collected_at)
            if post.post_id in run_seen or not seen_store.is_new(post.post_id):
                skip_count += 1
                continue
            run_seen.add(post.post_id)
            seen_store.mark_seen(post.post_id)
            new_posts.append(post)
            new_count += 1
        print(
            f"[bluesky:{keyword}] 取得: {len(raw_posts)}件 "
            f"/ 新規: {new_count}件 / スキップ: {skip_count}件"
        )

    output_path = append_jsonl([p.to_dict() for p in new_posts], data_dir, today)
    seen_store.save()
    print(f"合計 {len(new_posts)} 件を {output_path} に保存しました。")
