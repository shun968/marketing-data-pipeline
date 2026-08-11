"""ユースケースが必要とする読み取りクエリ。

SQLはここに置き、ユースケース側は「行の列」を受け取って計算・整形する。
こうしておくと、集計や判定のテストがDBファイル無しで書ける（ADR-0011）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb


def keyword_rows(conn: duckdb.DuckDBPyConnection, platform: str) -> list[tuple[list[str], str]]:
    """キーワード集計の材料。(matched_keywords, text) の列。

    1投稿が複数キーワードにマッチしうるため、展開はユースケース側で行う。
    """
    return conn.execute(
        "SELECT matched_keywords, text FROM posts WHERE platform = ?", [platform]
    ).fetchall()
