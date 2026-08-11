"""抽出結果の取り込み（F-05, F-06, F-08）。

検証を通った行だけを insights へ入れ、`posts.extraction_status` を done にする。
拒否した行は `<batch-id>.errors.jsonl` へ隔離し、該当投稿は batched のまま残す。
残すことで次回の再バッチ対象になり、取りこぼしが消えない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ...domain.insight import Insight, ValidationError, validate
from ..jsonl import write_jsonl

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# 同じ投稿を再抽出したら上書きする。extractor_version を上げた際の
# 入れ直し（design.md §4.3 再抽出）がこれで成立する
#
# **要約が変わったら埋め込みを捨てる。** embed は `embedding IS NULL` の行しか
# 拾わないため、ここで消さないと新しい要約に対して古い本文のベクトルが
# 残り続け、以後どの実行でも更新されない。検索順位が旧版の要約で決まる。
# 要約が同じときに消さないのは、再埋め込みが無駄になるだけだからである。
_UPSERT = """
INSERT INTO insights (
    post_id, insight_type, domain, summary, pain_level,
    monetizable, competitors, confidence, extractor_version, extracted_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (post_id) DO UPDATE SET
    insight_type      = excluded.insight_type,
    domain            = excluded.domain,
    summary           = excluded.summary,
    pain_level        = excluded.pain_level,
    monetizable       = excluded.monetizable,
    competitors       = excluded.competitors,
    confidence        = excluded.confidence,
    extractor_version = excluded.extractor_version,
    extracted_at      = excluded.extracted_at,
    embedding         = CASE
        WHEN insights.summary IS DISTINCT FROM excluded.summary THEN NULL
        ELSE insights.embedding
    END,
    embedding_model   = CASE
        WHEN insights.summary IS DISTINCT FROM excluded.summary THEN NULL
        ELSE insights.embedding_model
    END
"""


@dataclass(frozen=True)
class LoadResult:
    batch_id: str
    accepted: int
    rejected: int
    errors_path: Path | None
    embeddings_cleared: int = 0
    """要約が変わって捨てたベクトルの件数。

    黙って捨てると、その投稿は `embed` を回すまで `search` の結果から消える。
    件数を返さないと運用者に気づく手段が無い。
    """


def _embedded_count(conn: duckdb.DuckDBPyConnection, post_ids: list[str]) -> int:
    if not post_ids:
        return 0
    placeholders = ", ".join("?" * len(post_ids))
    return conn.execute(
        "SELECT count(*) FROM insights "
        f"WHERE embedding IS NOT NULL AND post_id IN ({placeholders})",
        post_ids,
    ).fetchone()[0]


def _batch_post_ids(batch_path: Path) -> set[str]:
    """バッチに含まれていた post_id。ハルシネーション検出の照合元。

    DBの batched ではなくバッチファイルを正とする。セッションが実際に読んだのは
    このファイルであり、照合はその内容に対して行うのが筋である。
    """
    ids = set()
    with batch_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["id"])
    return ids


def load(
    conn: duckdb.DuckDBPyConnection,
    extract_dir: Path,
    batch_id: str,
    *,
    allowed_domains: frozenset[str],
    now: datetime | None = None,
) -> LoadResult:
    now = now or datetime.now(UTC)
    batch_path = extract_dir / f"{batch_id}.jsonl"
    result_path = extract_dir / f"{batch_id}.result.jsonl"

    if not batch_path.exists():
        raise FileNotFoundError(f"バッチファイルが無い: {batch_path}")
    if not result_path.exists():
        raise FileNotFoundError(f"抽出結果が無い: {result_path}")

    version_row = conn.execute(
        "SELECT extractor_version FROM extraction_batches WHERE batch_id = ?", [batch_id]
    ).fetchone()
    if version_row is None:
        raise ValueError(f"未登録のバッチ: {batch_id}")
    version = version_row[0]

    expected = _batch_post_ids(batch_path)
    seen: set[str] = set()
    accepted: list[Insight] = []
    errors: list[dict] = []

    with result_path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append({"line": line_no, "reason": f"JSONとして読めない: {e}"})
                continue

            try:
                insight = validate(record, allowed_domains=allowed_domains)
            except ValidationError as e:
                errors.append({"line": line_no, "post_id": record.get("post_id"), "reason": str(e)})
                continue

            # バッチに無いIDは、抽出側が作った(ハルシネーションした)値である。
            # 通すと存在しない投稿の洞察がDBに入り、追跡できなくなる
            if insight.post_id not in expected:
                errors.append(
                    {
                        "line": line_no,
                        "post_id": insight.post_id,
                        "reason": "このバッチに含まれない post_id",
                    }
                )
                continue
            if insight.post_id in seen:
                errors.append(
                    {"line": line_no, "post_id": insight.post_id, "reason": "同一 post_id の重複"}
                )
                continue

            seen.add(insight.post_id)
            accepted.append(insight)

    embeddings_cleared = 0
    if accepted:
        # 捨てた件数は前後の差で数える。_UPSERT の CASE と同じ条件をここに
        # 書き直すと、片方だけ直したときに数字が黙って嘘になる。
        # この UPSERT はベクトルを消すことしかしないため、差は必ず捨てた分に等しい
        post_ids = [i.post_id for i in accepted]
        before = _embedded_count(conn, post_ids)

        conn.executemany(
            _UPSERT,
            [
                [
                    i.post_id,
                    i.insight_type,
                    i.domain,
                    i.summary,
                    i.pain_level,
                    i.monetizable,
                    i.competitors,
                    i.confidence,
                    version,
                    now.replace(tzinfo=None),
                ]
                for i in accepted
            ],
        )
        embeddings_cleared = before - _embedded_count(conn, post_ids)

        conn.executemany(
            "UPDATE posts SET extraction_status = 'done' WHERE id = ?",
            [[i.post_id] for i in accepted],
        )

    conn.execute(
        "UPDATE extraction_batches SET loaded_at = ?, loaded_count = ? WHERE batch_id = ?",
        [now.replace(tzinfo=None), len(accepted), batch_id],
    )

    errors_path = None
    if errors:
        errors_path = extract_dir / f"{batch_id}.errors.jsonl"
        write_jsonl(errors, errors_path)

    return LoadResult(
        batch_id=batch_id,
        accepted=len(accepted),
        rejected=len(errors),
        errors_path=errors_path,
        embeddings_cleared=embeddings_cleared,
    )


def status(conn: duckdb.DuckDBPyConnection) -> dict:
    """抽出待ち件数と未取り込みバッチの一覧。"""
    counts = dict(
        conn.execute(
            "SELECT extraction_status, count(*) FROM posts GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )
    pending_batches = conn.execute(
        """
        SELECT batch_id, created_at, post_count, extractor_version
        FROM extraction_batches WHERE loaded_at IS NULL ORDER BY created_at
        """
    ).fetchall()
    by_domain = conn.execute(
        """
        SELECT coalesce(domain, '(none)'), count(*)
        FROM insights GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    return {"posts": counts, "unloaded_batches": pending_batches, "insights_by_domain": by_domain}
