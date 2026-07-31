from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import requests

from ..common.config import YouTubeConfig
from ..common.seen_store import SeenStore
from ..common.storage import append_jsonl
from .client import search_videos
from .models import YouTubeVideo


def run(config: YouTubeConfig, data_dir: Path, state_path: Path) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    seen_store = SeenStore(state_path, today=today)
    run_seen: set[str] = set()
    failed_keywords: list[str] = []
    total_new = 0
    output_path: Path | None = None

    for keyword in config.keywords:
        # 1キーワードの失敗で run 全体を落とさない。
        # ここで落とすと消費済みクォータが無駄になる。
        try:
            items = search_videos(
                config.api_key,
                keyword,
                config.order,
                config.max_results_per_keyword,
                config.region_code,
                config.relevance_language,
            )
        except requests.RequestException as e:
            print(f"[youtube:{keyword}] 取得失敗のためスキップ: {e}")
            failed_keywords.append(keyword)
            continue

        new_videos: list[YouTubeVideo] = []
        skip_count = 0
        malformed_count = 0
        for item in items:
            # APIレスポンスの形が想定と違っても、その動画だけを捨てて処理を続ける。
            try:
                video = YouTubeVideo.from_item(item, keyword, collected_at)
            except (KeyError, TypeError, ValueError) as e:
                malformed_count += 1
                print(f"  [youtube:{keyword}] 不正な動画をスキップ: {e}")
                continue

            if video.video_id in run_seen or not seen_store.is_new(video.video_id):
                skip_count += 1
                continue
            run_seen.add(video.video_id)
            new_videos.append(video)

        # キーワード単位で保存する。ここでまとめずrun末尾に持ち越すと、
        # 以降のキーワードで予期しない例外が出た際に収集済みの全件を失う。
        # JSONLを先に書き、成功してからSeenStoreへ記録する。逆順にすると
        # 書き込み前にプロセスが落ちた場合、その動画を二度と収集できなくなる。
        if new_videos:
            output_path = append_jsonl([v.to_dict() for v in new_videos], data_dir, today)
            for video in new_videos:
                seen_store.mark_seen(video.video_id)
            seen_store.save()
            total_new += len(new_videos)

        message = (
            f"[youtube:{keyword}] 取得: {len(items)}件 "
            f"/ 新規: {len(new_videos)}件 / スキップ: {skip_count}件"
        )
        if malformed_count:
            message += f" / 不正: {malformed_count}件"
        print(message)

    if output_path is None:
        print(f"新規の動画はありませんでした。(収集先: {data_dir})")
    else:
        print(f"合計 {total_new} 件を {output_path} に保存しました。")

    if failed_keywords:
        print(
            f"取得に失敗したキーワード {len(failed_keywords)}/{len(config.keywords)} 件: "
            f"{', '.join(failed_keywords)}"
        )
