"""JSONL → posts のロード。

冪等性（F-01）: 主キー衝突時は既存行を残し、`matched_keywords` だけ和集合へ広げる。
同じファイルを何度ロードしても件数も内容も変わらない。

不正な行はスキップして処理を続ける（design.md §5.5）。1行の破損で
そのファイルの残り全部を失わない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .adapters import ADAPTERS, AdapterError, PostRow

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# 既存行は上書きしない。ヒットしたキーワードだけを足していく。
# 同じ投稿が複数キーワードで引っかかるため、どの語で見つかったかは
# 後からキーワードの効き目を評価する材料になる（config/keywords.yaml の改訂履歴）
_UPSERT = """
INSERT INTO posts (
    id, platform, native_id, author_id, author_handle, text, url, lang,
    posted_at, collected_at, matched_keywords, metrics, raw, extraction_status
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
ON CONFLICT (id) DO UPDATE SET
    matched_keywords = list_distinct(
        list_concat(posts.matched_keywords, excluded.matched_keywords)
    )
"""


@dataclass(frozen=True)
class LoadResult:
    files: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total_rows(self) -> int:
        return self.inserted + self.updated


def _iter_jsonl_files(data_dir: Path, platform: str, since: date | None) -> list[Path]:
    platform_dir = data_dir / platform
    if not platform_dir.is_dir():
        return []

    files = sorted(platform_dir.glob("*.jsonl"))
    if since is None:
        return files

    # ファイル名が収集日（YYYY-MM-DD.jsonl）。名前で切れるので中身を開かずに絞れる
    selected = []
    for path in files:
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            # 命名規則から外れたファイルは判断できない。落とさず対象に含める
            selected.append(path)
            continue
        if file_date >= since:
            selected.append(path)
    return selected


def _row_values(row: PostRow) -> list:
    return [
        row.id,
        row.platform,
        row.native_id,
        row.author_id,
        row.author_handle,
        row.text,
        row.url,
        row.lang,
        row.posted_at,
        row.collected_at,
        row.matched_keywords,
        row.metrics,
        row.raw,
    ]


def insert_records(
    conn: duckdb.DuckDBPyConnection,
    platform: str,
    records: list[dict],
) -> int:
    """収集直後のレコードを posts へ入れる。投入を試みた件数を返す。

    ロードと同じアダプタ・同じSQLを通す。収集経路とロード経路で正規化が
    分かれると、`db load` で再構築した内容が収集時と食い違う（F-04が崩れる）。
    """
    adapter = ADAPTERS[platform]
    rows = []
    for record in records:
        try:
            rows.append(_row_values(adapter(record)))
        except (AdapterError, KeyError, TypeError) as e:
            print(f"  [{platform}] DBへの投入をスキップ: {e}")

    if rows:
        conn.executemany(_UPSERT, rows)
    return len(rows)


def load_platform(
    conn: duckdb.DuckDBPyConnection,
    data_dir: Path,
    platform: str,
    *,
    since: date | None = None,
) -> LoadResult:
    adapter = ADAPTERS[platform]
    files = _iter_jsonl_files(data_dir, platform, since)

    inserted = 0
    updated = 0
    skipped = 0

    for path in files:
        rows: list[list] = []
        with path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    rows.append(_row_values(adapter(record)))
                except (json.JSONDecodeError, AdapterError, KeyError, TypeError) as e:
                    # 本文は出さない。どのファイルの何行目かだけを残す
                    print(f"  [{platform}] {path.name}:{line_no} を読めないためスキップ: {e}")
                    skipped += 1

        if not rows:
            continue

        # 何件が新規かを数えるため、投入前後の件数差を取る。
        # ON CONFLICT の戻り値だけでは新規と更新を区別できない
        before = conn.execute("SELECT count(*) FROM posts").fetchone()[0]
        conn.executemany(_UPSERT, rows)
        after = conn.execute("SELECT count(*) FROM posts").fetchone()[0]

        new_rows = after - before
        inserted += new_rows
        updated += len(rows) - new_rows

    return LoadResult(files=len(files), inserted=inserted, updated=updated, skipped=skipped)


def load_all(
    conn: duckdb.DuckDBPyConnection,
    data_dir: Path,
    *,
    since: date | None = None,
) -> dict[str, LoadResult]:
    """全プラットフォームをロードする。

    `--since` を既定で持たないのは、ロードが冪等で全件走査が安いためである。
    ロード済みファイルを記録するテーブルを別に持つと、そのテーブルと実際の
    posts が乖離したときに原因を追えなくなる。判断の材料は posts だけにする。
    """
    return {platform: load_platform(conn, data_dir, platform, since=since) for platform in ADAPTERS}


def known_ids(conn: duckdb.DuckDBPyConnection, platform: str) -> set[str]:
    """収集時の重複判定に使う既知の native_id 集合（ADR-0004）。

    SeenStore の代替。60日のプルーニングが無いため、全期間の投稿を弾ける。
    """
    rows = conn.execute("SELECT native_id FROM posts WHERE platform = ?", [platform]).fetchall()
    return {row[0] for row in rows}
