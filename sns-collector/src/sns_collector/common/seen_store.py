from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PRUNE_AFTER_DAYS = 60


class SeenStore:
    """cron等での定期実行を前提に、run跨ぎの既知IDを永続化する。"""

    def __init__(self, path: Path, today: date | None = None) -> None:
        self._path = path
        self._today = today or datetime.now(UTC).date()
        self._seen: dict[str, str] = self._load()
        self._prune()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return raw.get("seen", {})

    def _prune(self) -> None:
        cutoff = self._today - timedelta(days=PRUNE_AFTER_DAYS)
        self._seen = {
            item_id: first_seen
            for item_id, first_seen in self._seen.items()
            if date.fromisoformat(first_seen) >= cutoff
        }

    def is_new(self, item_id: str) -> bool:
        return item_id not in self._seen

    def mark_seen(self, item_id: str) -> None:
        if item_id not in self._seen:
            self._seen[item_id] = self._today.isoformat()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seen": self._seen}
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
