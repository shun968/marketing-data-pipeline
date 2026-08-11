"""収集ユースケースの回帰テスト。

**このファイルが全収集元の失敗モードを担保する。** 以前は収集元ごとに
6ファイルへ同じテストが書き写されており、7つ目を足す人がどれか1つを
落とす余地があった（ADR-0011）。

DB・HTTP・ファイルは出てこない。ユースケースが受け取るのは関数だけなので、
`unittest.mock.patch` も要らない。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sns_collector.domain.collect import (
    CollectPorts,
    CollectTask,
    InsertOutcome,
    Record,
    SourceUnavailable,
)
from sns_collector.usecase.collect import collect

OUTPUT = Path("/tmp/collected.jsonl")


class FakeStore:
    """保存先の記録。JSONLとDBを分けて持ち、書き込み順も残す。"""

    def __init__(self, known: set[str] | None = None, failed: int = 0) -> None:
        self.known = known or set()
        self.failed = failed
        self.saved: list[dict] = []
        self.stored: list[dict] = []
        self.hits: list[tuple[list[str], str]] = []
        self.messages: list[str] = []
        self.order: list[str] = []

    def ports(self) -> CollectPorts:
        def save(payloads: list[dict]) -> Path:
            self.saved.extend(payloads)
            self.order.append("save")
            return OUTPUT

        def store(payloads: list[dict]) -> InsertOutcome:
            self.stored.extend(payloads)
            self.order.append("store")
            return InsertOutcome(inserted=len(payloads), failed=self.failed)

        return CollectPorts(
            known_ids=lambda: set(self.known),
            save_records=save,
            store_records=store,
            record_keyword_hits=lambda ids, kw: self.hits.append((list(ids), kw)),
            notify=self.messages.append,
        )


def _task(label: str, items: list[dict], *, keyword: str = "kw") -> CollectTask:
    def parse(raw: dict) -> Record | None:
        # 収集対象外は None。読めない行は例外（どちらも収集を止めない）
        if raw.get("skip"):
            return None
        return Record(native_id=raw["id"], payload=dict(raw))

    return CollectTask(label=label, keyword=keyword, fetch=lambda: items, parse=parse)


def test_新規だけを保存し既知は記録だけ残す():
    store = FakeStore(known={"known-1"})
    task = _task("t", [{"id": "new-1"}, {"id": "known-1"}])

    summary = collect([task], store.ports())

    assert [r["id"] for r in store.saved] == ["new-1"]
    assert store.hits == [(["known-1"], "kw")]
    assert summary.total_new == 1
    assert summary.output_path == OUTPUT


def test_同一run内の重複は1度しか保存しない():
    store = FakeStore()
    tasks = [_task("t1", [{"id": "a"}]), _task("t2", [{"id": "a"}])]

    summary = collect(tasks, store.ports())

    assert [r["id"] for r in store.saved] == ["a"]
    assert summary.total_new == 1


def test_JSONLを書いてからDBへ入れる():
    """逆順にすると、書き込み前に落ちた投稿を二度と収集できなくなる。

    DBに既知として記録済みのため、次回の実行でスキップされる。
    """
    store = FakeStore()

    collect([_task("t", [{"id": "a"}])], store.ports())

    assert store.order == ["save", "store"]


def test_取得失敗したタスクは他のタスクを巻き込まない():
    store = FakeStore()

    def failing() -> list[dict]:
        raise SourceUnavailable("503 Server Error")

    tasks = [
        _task("ok", [{"id": "a"}]),
        CollectTask(label="ng", keyword="kw", fetch=failing, parse=lambda raw: None),
        _task("ok2", [{"id": "b"}]),
    ]

    summary = collect(tasks, store.ports())

    assert [r["id"] for r in store.saved] == ["a", "b"]
    assert summary.failed_labels == ["ng"]
    assert summary.task_count == 3


def test_想定外の例外が貫通してもそれ以前の保存は残る():
    """SourceUnavailable以外は握り潰さない。ただし保存済みは失わない。"""
    store = FakeStore()

    def exploding() -> list[dict]:
        raise RuntimeError("想定外")

    tasks = [
        _task("ok", [{"id": "a"}]),
        CollectTask(label="boom", keyword="kw", fetch=exploding, parse=lambda raw: None),
    ]

    with pytest.raises(RuntimeError):
        collect(tasks, store.ports())

    assert [r["id"] for r in store.saved] == ["a"]


def test_読めない1件を捨てて残りは保存する():
    store = FakeStore()
    # id が無い行は parse が KeyError を投げる
    task = _task("t", [{"broken": True}, {"id": "a"}, {"id": "b"}])

    collect([task], store.ports())

    assert [r["id"] for r in store.saved] == ["a", "b"]
    assert any("不正な投稿をスキップ" in m for m in store.messages)


def test_収集対象外は不正データと区別して数える():
    """parse の None は「読めたが対象ではない」。hnjobs が返信を落とすのに使う。"""
    store = FakeStore()
    task = _task("t", [{"id": "x", "skip": True}, {"id": "a"}])

    collect([task], store.ports())

    assert [r["id"] for r in store.saved] == ["a"]
    assert any("対象外: 1件" in m for m in store.messages)
    assert not any("不正" in m for m in store.messages)


def test_DBへ入らなかった件数を知らせる():
    """JSONLに在るのにDBに無い投稿は、次回も新規と判定されて再収集される。"""
    store = FakeStore(failed=2)

    collect([_task("t", [{"id": "a"}])], store.ports())

    assert any("2件がDBに入らなかった" in m for m in store.messages)


def test_新規が無ければ出力先を持たない():
    store = FakeStore(known={"a"})

    summary = collect([_task("t", [{"id": "a"}])], store.ports())

    assert summary.output_path is None
    assert summary.total_new == 0


def test_ログの語は収集元ごとに差し替えられる():
    store = FakeStore()

    collect([_task("t", [{"broken": True}])], store.ports(), unit="動画")

    assert any("不正な動画をスキップ" in m for m in store.messages)
