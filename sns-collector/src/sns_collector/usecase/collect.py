"""収集ユースケース。全プラットフォームで共通。

収集元ごとに違うのは「何を検索するか」と「生レスポンスをどう読むか」だけで、
それは `CollectTask` として adapter から渡される（ADR-0011）。
ここには収集元固有の知識を持ち込まない。

**このファイルには、収集データを失わないための3つの隔離が入っている。**
`sns-collector/CLAUDE.md` が挙げる失敗モードへの対策であり、以前は
収集元ごとに6ファイルへ書き写されていた。7つ目を足す人がどれか1つを
落とす余地を無くすため、1箇所へ集めてある。
"""

from __future__ import annotations

from pathlib import Path

from ..domain.collect import (
    CollectPorts,
    CollectSummary,
    CollectTask,
    Record,
    SourceUnavailable,
)


def collect(tasks: list[CollectTask], ports: CollectPorts, *, unit: str = "投稿") -> CollectSummary:
    """タスクを順に実行し、既知でないものだけを保存する。

    unit はログの語（「投稿」「動画」「求人」）。集計や判定には使わない。
    """
    # 起動時に1回だけ引く。1件ずつ問い合わせると、タスク数×件数のクエリになる
    seen = ports.known_ids()
    run_seen: set[str] = set()
    failed_labels: list[str] = []
    total_new = 0
    output_path: Path | None = None

    for task in tasks:
        # 隔離1: 1タスクの取得失敗で run 全体を落とさない。
        # 取りこぼした分は次回の定期実行でカバーされる。
        try:
            raw_items = task.fetch()
        except SourceUnavailable as e:
            ports.notify(f"[{task.label}] 取得失敗のためスキップ: {e}")
            failed_labels.append(task.label)
            continue

        known_hits: list[str] = []
        new_records: list[Record] = []
        skip_count = 0
        excluded_count = 0
        malformed_count = 0

        for raw in raw_items:
            # 隔離2: レスポンスの形が想定と違っても、その1件だけを捨てて続ける。
            try:
                record = task.parse(raw)
            except (KeyError, TypeError, ValueError) as e:
                malformed_count += 1
                ports.notify(f"  [{task.label}] 不正な{unit}をスキップ: {e}")
                continue

            # parse が None を返すのは「読めたが収集対象ではない」場合。
            # 不正データ（上）と区別して数える
            if record is None:
                excluded_count += 1
                continue

            if record.native_id in run_seen:
                skip_count += 1
                continue
            if record.native_id in seen:
                # JSONLには書かないが、この語でも見つかった事実はDBへ残す
                known_hits.append(record.native_id)
                skip_count += 1
                continue
            run_seen.add(record.native_id)
            new_records.append(record)

        # 隔離3: タスク単位で保存する。ここでまとめずrun末尾に持ち越すと、
        # 以降のタスクで予期しない例外が出た際に収集済みの全件を失う。
        # JSONLを先に書き、成功してからDBへ入れる。逆順にすると
        # 書き込み前にプロセスが落ちた場合、その投稿を二度と収集できなくなる
        # （DBに既知として記録済みなのでスキップされる）。
        if new_records:
            payloads = [r.payload for r in new_records]
            output_path = ports.save_records(payloads)
            outcome = ports.store_records(payloads)
            if outcome.failed:
                ports.notify(
                    f"  [{task.label}] {outcome.failed}件がDBに入らなかった。"
                    "重複判定できず次回も再収集される"
                )
            seen.update(r.native_id for r in new_records)
            total_new += len(new_records)

        ports.record_keyword_hits(known_hits, task.keyword)

        message = (
            f"[{task.label}] 取得: {len(raw_items)}件 "
            f"/ 新規: {len(new_records)}件 / スキップ: {skip_count}件"
        )
        if excluded_count:
            message += f" / 対象外: {excluded_count}件"
        if malformed_count:
            message += f" / 不正: {malformed_count}件"
        ports.notify(message)

    return CollectSummary(
        total_new=total_new,
        output_path=output_path,
        failed_labels=failed_labels,
        task_count=len(tasks),
    )
