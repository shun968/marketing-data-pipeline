from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests

from ..common.config import ConfigError, HackerNewsJobsConfig
from ..common.storage import append_jsonl
from ..db import connect, insert_records, known_ids, record_keyword_hits
from .client import list_threads, search_thread
from .models import (
    THREAD_KINDS,
    HackerNewsJobPost,
    is_job_entry,
    thread_authors,
    thread_kind,
)

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb


def run(config: HackerNewsJobsConfig, data_dir: Path, db_path: Path) -> None:
    # 綴り違いを「対象0件」として静かに通さない。設定ミスは実行前に落とす
    unknown = [k for k in config.thread_kinds if k not in THREAD_KINDS]
    if unknown:
        raise ConfigError(
            f"未知の thread_kinds: {', '.join(unknown)}。"
            f"使えるのは {', '.join(THREAD_KINDS)} です。"
        )
    if not config.thread_kinds:
        raise ConfigError("hnjobs.thread_kinds が空です。収集対象のスレッドがありません。")

    # 重複判定はDBの posts に一本化した（ADR-0004）
    with connect(db_path) as conn:
        _run_with_db(config, data_dir, conn)


def _select_threads(config: HackerNewsJobsConfig) -> list[tuple[dict[str, Any], str]]:
    """対象種別の月次スレッドを、種別ごとに thread_limit 件まで新着順で選ぶ。

    上限は種別ごとに数える。全体で数えると、毎月立つ求人スレッドだけで枠が埋まり、
    本数の少ない案件スレッドが一度も収集されないまま終わる。

    1つのアカウントが複数種別を立てるため（whoishiring は hiring と hired）、
    絞り込みで落ちる分を見越して多めに引く。
    """
    selected: list[tuple[dict[str, Any], str]] = []
    taken: Counter[str] = Counter()

    for author in thread_authors(config.thread_kinds):
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
            print(f"[hnjobs] 種別 {kind} のスレッドが1件も見つかりませんでした。")
    return selected


def _run_with_db(
    config: HackerNewsJobsConfig, data_dir: Path, conn: duckdb.DuckDBPyConnection
) -> None:
    today = datetime.now(UTC).date()
    collected_at = datetime.now(UTC)

    # スレッド一覧はこの run の前提。取れなければ収集対象が決まらないため、
    # ここでは捕捉せず呼び出し元へ投げる（この時点で失うデータはまだ無い）。
    threads = _select_threads(config)
    if not threads:
        print(f"対象スレッドが見つかりませんでした。(種別: {', '.join(config.thread_kinds)})")
        return

    # 起動時に1回だけ引く。1件ずつ問い合わせると、スレッド数×キーワード数×件数になる
    seen = known_ids(conn, "hnjobs")
    run_seen: set[str] = set()
    failed: list[str] = []
    total_new = 0
    output_path: Path | None = None

    for thread, kind in threads:
        story_id = str(thread["objectID"])
        title = thread.get("title") or story_id

        for keyword in config.keywords:
            # 1組の失敗で run 全体を落とさない。
            # 取りこぼした分は次回の定期実行でカバーされる。
            try:
                hits = search_thread(story_id, keyword, config.hits_per_page)
            except requests.RequestException as e:
                print(f"[hnjobs:{title}:{keyword}] 取得失敗のためスキップ: {e}")
                failed.append(f"{title}/{keyword}")
                continue

            known_hits: list[str] = []
            new_items: list[HackerNewsJobPost] = []
            skip_count = 0
            reply_count = 0
            malformed_count = 0
            for hit in hits:
                # スレッド直下でないものは求人票ではなく議論。DBへ入れない
                if not is_job_entry(hit):
                    reply_count += 1
                    continue

                # APIレスポンスの形が想定と違っても、その1件だけを捨てて処理を続ける。
                try:
                    item = HackerNewsJobPost.from_hit(hit, keyword, thread, kind, collected_at)
                except (KeyError, TypeError, ValueError) as e:
                    malformed_count += 1
                    print(f"  [hnjobs:{title}:{keyword}] 不正な投稿をスキップ: {e}")
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

            # (スレッド, キーワード)単位で保存する。ここでまとめずrun末尾に持ち越すと、
            # 以降の組で予期しない例外が出た際に収集済みの全件を失う。
            # JSONLを先に書き、成功してからDBへ入れる。逆順にすると
            # 書き込み前にプロセスが落ちた場合、その投稿を二度と収集できなくなる
            # （DBに既知として記録済みなのでスキップされる）。
            if new_items:
                records = [i.to_dict() for i in new_items]
                output_path = append_jsonl(records, data_dir, today)
                result = insert_records(conn, "hnjobs", records)
                if result.failed:
                    print(
                        f"  [hnjobs:{title}:{keyword}] {result.failed}件がDBに入らなかった。"
                        "重複判定できず次回も再収集される"
                    )
                seen.update(i.item_id for i in new_items)
                total_new += len(new_items)

            record_keyword_hits(conn, "hnjobs", known_hits, keyword)

            message = (
                f"[hnjobs:{title}:{keyword}] 取得: {len(hits)}件 "
                f"/ 新規: {len(new_items)}件 / スキップ: {skip_count}件"
            )
            if reply_count:
                message += f" / 返信除外: {reply_count}件"
            if malformed_count:
                message += f" / 不正: {malformed_count}件"
            print(message)

    if output_path is None:
        print(f"新規の求人はありませんでした。(収集先: {data_dir})")
    else:
        print(f"合計 {total_new} 件を {output_path} に保存しました。")

    if failed:
        total_pairs = len(threads) * len(config.keywords)
        print(f"取得に失敗した組 {len(failed)}/{total_pairs} 件: {', '.join(failed)}")
