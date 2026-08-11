"""DuckDBのスキーマ定義とマイグレーション。

前方向のみのマイグレーションとする（design.md §5.4）。
ロールバックはバックアップからの復元で行うため、逆方向のDDLは持たない。

インデックスは張っていない。年間10万件規模ではテーブルスキャンで足り、
必要になってから実測して追加する（design.md §5.3）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# マイグレーションは (version, 説明, SQL) の並び。**既存の要素を書き換えないこと。**
# 適用済みのDBには過去のSQLがそのまま効いているため、書き換えると
# 新規作成したDBと既存DBでスキーマが食い違う。変更は必ず末尾へ追加する。
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "posts / insights / edges / extraction_batches を作成する",
        """
        CREATE TABLE IF NOT EXISTS posts (
            id                VARCHAR PRIMARY KEY,
            platform          VARCHAR NOT NULL,
            native_id         VARCHAR NOT NULL,
            author_id         VARCHAR,
            author_handle     VARCHAR,
            text              VARCHAR,
            url               VARCHAR,
            lang              VARCHAR,
            posted_at         TIMESTAMP,
            collected_at      TIMESTAMP,
            matched_keywords  VARCHAR[],
            metrics           JSON,
            raw               JSON,
            extraction_status VARCHAR NOT NULL DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS insights (
            post_id           VARCHAR PRIMARY KEY,
            insight_type      VARCHAR NOT NULL,
            domain            VARCHAR,
            summary           VARCHAR,
            pain_level        TINYINT,
            monetizable       BOOLEAN,
            competitors       VARCHAR[],
            confidence        FLOAT,
            extractor_version VARCHAR,
            extracted_at      TIMESTAMP,
            embedding         FLOAT[]
        );

        CREATE TABLE IF NOT EXISTS edges (
            src_type    VARCHAR NOT NULL,
            src_id      VARCHAR NOT NULL,
            dst_type    VARCHAR NOT NULL,
            dst_id      VARCHAR NOT NULL,
            edge_type   VARCHAR NOT NULL,
            weight      FLOAT,
            observed_at TIMESTAMP,
            PRIMARY KEY (src_type, src_id, dst_type, dst_id, edge_type)
        );

        CREATE TABLE IF NOT EXISTS extraction_batches (
            batch_id          VARCHAR PRIMARY KEY,
            created_at        TIMESTAMP,
            post_count        INTEGER,
            extractor_version VARCHAR,
            loaded_at         TIMESTAMP,
            loaded_count      INTEGER
        );
        """,
    ),
    (
        2,
        "insights.embedding_model を追加する",
        """
        ALTER TABLE insights ADD COLUMN embedding_model VARCHAR;
        """,
    ),
]

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL,
    note       VARCHAR
);
"""


def latest_version() -> int:
    return max((version for version, _, _ in MIGRATIONS), default=0)


def current_version(conn: duckdb.DuckDBPyConnection) -> int:
    conn.execute(_SCHEMA_VERSION_DDL)
    row = conn.execute("SELECT max(version) FROM schema_version").fetchone()
    return row[0] if row and row[0] is not None else 0


def migrate(conn: duckdb.DuckDBPyConnection) -> list[int]:
    """未適用のマイグレーションを順に適用し、適用したバージョンを返す。

    何度呼んでも結果が変わらない。収集コマンドからも呼ばれるため、
    `db init` を忘れた状態でcronが落ちることがない。
    """
    applied_from = current_version(conn)
    applied: list[int] = []

    for version, note, sql in sorted(MIGRATIONS):
        if version <= applied_from:
            continue
        # 1バージョンを1トランザクションにする。途中で落ちたとき、
        # DDLだけ通って schema_version が未記録という状態を作らない
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at, note) VALUES (?, now(), ?)",
                [version, note],
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)

    return applied


def database_path(data_dir: Path) -> Path:
    return data_dir / "analysis.duckdb"
