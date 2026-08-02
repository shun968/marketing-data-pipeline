"""DuckDBへの接続。

DuckDBは組み込み型で常駐プロセスを持たない（ADR-0001）。接続は単なる
ファイルオープンであり、プロセス内で1本開いて閉じるだけでよい。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from .schema import migrate


@contextmanager
def connect(db_path: Path, *, ensure_schema: bool = True) -> Iterator[duckdb.DuckDBPyConnection]:
    """DBへ接続する。既定でスキーマを最新へ揃える。

    ensure_schema を既定で有効にしているのは、収集コマンドがDBの存在に
    依存するようになったため（ADR-0004）。`db init` の実行漏れで
    cronが落ちる経路を作らない。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        if ensure_schema:
            migrate(conn)
        yield conn
    finally:
        conn.close()
