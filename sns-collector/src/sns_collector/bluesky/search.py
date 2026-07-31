from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import requests

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
    failed_keywords: list[str] = []
    total_new = 0
    output_path: Path | None = None

    for keyword in config.keywords:
        # 1キーワードの失敗で run 全体を落とさない。
        # 取りこぼしたキーワードは次回の定期実行でカバーされる。
        try:
            raw_posts = search_posts(keyword, config.sort, config.limit_per_keyword)
        except requests.RequestException as e:
            print(f"[bluesky:{keyword}] 取得失敗のためスキップ: {e}")
            failed_keywords.append(keyword)
            continue

        new_posts: list[BlueskyPost] = []
        skip_count = 0
        malformed_count = 0
        for raw_post in raw_posts:
            # APIレスポンスの形が想定と違っても、その投稿だけを捨てて処理を続ける。
            try:
                post = BlueskyPost.from_post(raw_post, keyword, collected_at)
            except (KeyError, TypeError, ValueError) as e:
                malformed_count += 1
                print(f"  [bluesky:{keyword}] 不正な投稿をスキップ: {e}")
                continue

            if post.post_id in run_seen or not seen_store.is_new(post.post_id):
                skip_count += 1
                continue
            run_seen.add(post.post_id)
            new_posts.append(post)

        # キーワード単位で保存する。ここでまとめずrun末尾に持ち越すと、
        # 以降のキーワードで予期しない例外が出た際に収集済みの全件を失う。
        # JSONLを先に書き、成功してからSeenStoreへ記録する。逆順にすると
        # 書き込み前にプロセスが落ちた場合、その投稿を二度と収集できなくなる。
        if new_posts:
            output_path = append_jsonl([p.to_dict() for p in new_posts], data_dir, today)
            for post in new_posts:
                seen_store.mark_seen(post.post_id)
            seen_store.save()
            total_new += len(new_posts)

        message = (
            f"[bluesky:{keyword}] 取得: {len(raw_posts)}件 "
            f"/ 新規: {len(new_posts)}件 / スキップ: {skip_count}件"
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
