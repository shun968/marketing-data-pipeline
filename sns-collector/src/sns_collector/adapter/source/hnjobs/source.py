from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ....domain.collect import CollectTask, Record
from ....domain.config import ConfigError, HackerNewsJobsConfig
from ...http import source_errors
from .client import list_threads, search_thread
from .dto import (
    THREAD_KINDS,
    HackerNewsJobPost,
    is_job_entry,
    thread_authors,
    thread_kind,
)


def tasks(
    config: HackerNewsJobsConfig, collected_at: datetime, notify: Callable[[str], None]
) -> list[CollectTask]:
    # 綴り違いを「対象0件」として静かに通さない。設定ミスは収集前に落とす
    unknown = [k for k in config.thread_kinds if k not in THREAD_KINDS]
    if unknown:
        raise ConfigError(
            f"未知の thread_kinds: {', '.join(unknown)}。"
            f"使えるのは {', '.join(THREAD_KINDS)} です。"
        )
    if not config.thread_kinds:
        raise ConfigError("hnjobs.thread_kinds が空です。収集対象のスレッドがありません。")

    threads = _select_threads(config, notify)
    if not threads:
        notify(f"対象スレッドが見つかりませんでした。(種別: {', '.join(config.thread_kinds)})")
        return []

    return [
        _task(config, thread, kind, keyword, collected_at)
        for thread, kind in threads
        for keyword in config.keywords
    ]


def _select_threads(
    config: HackerNewsJobsConfig, notify: Callable[[str], None]
) -> list[tuple[dict[str, Any], str]]:
    """対象種別の月次スレッドを、種別ごとに thread_limit 件まで新着順で選ぶ。

    上限は種別ごとに数える。全体で数えると、毎月立つ求人スレッドだけで枠が埋まり、
    本数の少ない案件スレッドが一度も収集されないまま終わる。

    1つのアカウントが複数種別を立てるため（whoishiring は hiring と hired）、
    絞り込みで落ちる分を見越して多めに引く。
    """
    selected: list[tuple[dict[str, Any], str]] = []
    taken: Counter[str] = Counter()

    for author in thread_authors(config.thread_kinds):
        with source_errors():
            hits = list_threads(author, config.thread_limit * len(THREAD_KINDS))
        for hit in hits:
            if "objectID" not in hit:
                continue
            kind = thread_kind(hit.get("title") or "")
            if kind is None or kind not in config.thread_kinds:
                continue
            if taken[kind] >= config.thread_limit:
                continue
            selected.append((hit, kind))
            taken[kind] += 1

    for kind in config.thread_kinds:
        if not taken[kind]:
            # 主催アカウントの引き継ぎが起きると、この種別だけが静かに0件になる
            notify(f"[hnjobs] 種別 {kind} のスレッドが1件も見つかりませんでした。")
    return selected


def _task(
    config: HackerNewsJobsConfig,
    thread: dict[str, Any],
    kind: str,
    keyword: str,
    collected_at: datetime,
) -> CollectTask:
    story_id = str(thread["objectID"])
    title = thread.get("title") or story_id

    def fetch() -> list[dict]:
        with source_errors():
            return search_thread(story_id, keyword, config.hits_per_page)

    def parse(raw: dict) -> Record | None:
        # スレッド直下でないものは求人票ではなく議論。収集対象から外す
        if not is_job_entry(raw):
            return None
        item = HackerNewsJobPost.from_hit(raw, keyword, thread, kind, collected_at)
        return Record(native_id=item.item_id, payload=item.to_dict())

    return CollectTask(label=f"hnjobs:{title}:{keyword}", keyword=keyword, fetch=fetch, parse=parse)
