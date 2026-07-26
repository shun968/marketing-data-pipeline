from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sns_collector.common.seen_store import SeenStore


def test_is_new_and_mark_seen(tmp_path: Path):
    store = SeenStore(tmp_path / "seen.json", today=date(2026, 7, 27))

    assert store.is_new("abc") is True
    store.mark_seen("abc")
    assert store.is_new("abc") is False


def test_save_persists_across_instances(tmp_path: Path):
    path = tmp_path / "seen.json"
    store = SeenStore(path, today=date(2026, 7, 27))
    store.mark_seen("abc")
    store.save()

    reloaded = SeenStore(path, today=date(2026, 7, 27))
    assert reloaded.is_new("abc") is False

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["seen"]["abc"] == "2026-07-27"


def test_prune_removes_entries_older_than_60_days(tmp_path: Path):
    path = tmp_path / "seen.json"
    path.write_text(
        json.dumps({"seen": {"old": "2026-01-01", "recent": "2026-07-01"}}),
        encoding="utf-8",
    )

    store = SeenStore(path, today=date(2026, 7, 27))

    assert store.is_new("old") is True
    assert store.is_new("recent") is False
