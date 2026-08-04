from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def append_jsonl(records: list[dict[str, Any]], output_dir: Path, today: date) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{today:%Y-%m-%d}.jsonl"

    with output_path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return output_path


def write_jsonl(records: list[dict[str, Any]], output_path: Path) -> Path:
    """1行1JSONで書き出す（上書き）。

    append_jsonl は日次の収集ファイルへ追記するためのもので、用途が違う。
    バッチ・エラーファイルは毎回作り直すため、追記すると前回分が混ざる。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return output_path
