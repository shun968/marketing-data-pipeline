"""抽出バッチの書き出し（F-07）。

`extraction_status='pending'` の投稿を取り出し、抽出対象のJSONLと
Claude Codeセッションへの作業指示Markdownを書く。

パイプラインからLLMを呼ばない（ADR-0003）。ここはファイルを書くだけで、
推論は人が開いたセッションが行う。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.storage import write_jsonl

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"


@dataclass(frozen=True)
class PrepareResult:
    batch_id: str
    post_count: int
    batch_path: Path
    instruction_path: Path


def _batch_id(now: datetime) -> str:
    return f"batch-{now:%Y%m%d-%H%M%S}"


def prompt_path(version: str) -> Path:
    return PROMPTS_DIR / f"extract-{version}.md"


# 抽出の既定はBlueskyだけ。
#
# YouTubeは供給シグナル（既存ソリューション・競合・市場の関心度）であり、
# 検索できるのは動画のメタデータに限られる（design.md §4.1）。そこへ
# 「未充足ニーズ／不満」の抽出を掛けても構造的にほぼ none にしかならない。
# 実測: 最初のバッチ20件のうち18件がYouTubeの製品デモで、全件 none だった。
# 供給側の分析はPhase 4のレポートで別途行う。
DEFAULT_PLATFORMS = ("bluesky",)


def _read_template(version: str) -> str:
    path = prompt_path(version)
    if not path.exists():
        available = sorted(
            p.stem.removeprefix("extract-") for p in PROMPTS_DIR.glob("extract-*.md")
        )
        raise FileNotFoundError(
            f"抽出プロンプトが無い: {path}（利用できる版: {', '.join(available) or 'なし'}）"
        )
    return path.read_text(encoding="utf-8")


def skip_unextractable(conn: duckdb.DuckDBPyConnection) -> int:
    """本文の無い投稿を skipped へ落とす。落とした件数を返す。

    バッチの選択から外すだけだと pending に残り続け、どのバッチにも載らないのに
    「抽出待ち」として数え続けられる（実測57件）。待ち件数が実態とずれ、
    進捗の判断ができなくなる。

    text は db load のたびにJSONLから入れ直されるため、原理上は後から本文が
    埋まることもありうる。その場合は手動で pending へ戻す。
    """
    before = conn.execute(
        "SELECT count(*) FROM posts WHERE extraction_status = 'skipped'"
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE posts SET extraction_status = 'skipped'
        WHERE extraction_status = 'pending'
          AND (text IS NULL OR length(trim(text)) = 0)
        """
    )
    after = conn.execute(
        "SELECT count(*) FROM posts WHERE extraction_status = 'skipped'"
    ).fetchone()[0]
    return after - before


def prepare(
    conn: duckdb.DuckDBPyConnection,
    extract_dir: Path,
    *,
    limit: int,
    version: str,
    domain_ids: list[str],
    platforms: tuple[str, ...] | list[str] = DEFAULT_PLATFORMS,
    now: datetime | None = None,
) -> PrepareResult | None:
    """未抽出の投稿をバッチへ書き出す。対象が無ければ None。"""
    if not platforms:
        raise ValueError("platforms を1つ以上指定する")

    # テンプレートの読み込みを先に済ませる。ファイルを書いた後で失敗すると、
    # どのバッチにも属さないJSONLが extract/ に残る
    template = _read_template(version)

    now = now or datetime.now(UTC)
    batch_id = _batch_id(now)

    skip_unextractable(conn)

    # 新しく収集したものから出す。
    # 投稿日の古い順にすると、初回収集で遡った過去分（最古は2009年）から処理する
    # ことになり、現在のキーワード設計と対応しない投稿にセッション時間を使う。
    # 収集日で並べれば、いま効いているキーワードが拾ったものから順に見られる。
    placeholders = ", ".join("?" for _ in platforms)
    rows = conn.execute(
        f"""
        SELECT id, platform, text, posted_at, matched_keywords
        FROM posts
        WHERE extraction_status = 'pending'
          AND platform IN ({placeholders})
          AND text IS NOT NULL AND length(trim(text)) > 0
        ORDER BY collected_at DESC NULLS LAST, id
        LIMIT ?
        """,
        [*platforms, limit],
    ).fetchall()

    if not rows:
        return None

    # 抽出に要らないフィールドは載せない。セッションのコンテキストを節約する
    records = [
        {
            "id": r[0],
            "platform": r[1],
            "text": r[2],
            "posted_at": r[3].isoformat() if r[3] else None,
            "matched_keywords": list(r[4] or []),
        }
        for r in rows
    ]
    post_ids = [r["id"] for r in records]

    extract_dir.mkdir(parents=True, exist_ok=True)
    batch_path = extract_dir / f"{batch_id}.jsonl"
    instruction_path = extract_dir / f"{batch_id}.md"
    result_path = extract_dir / f"{batch_id}.result.jsonl"

    write_jsonl(records, batch_path)

    instruction_path.write_text(
        template.replace("{batch_jsonl}", str(batch_path))
        .replace("{result_jsonl}", str(result_path))
        .replace("{domain_ids}", " | ".join(domain_ids)),
        encoding="utf-8",
    )

    # ファイルを書いてから状態を進める。逆順にすると、書き込み前に落ちた投稿が
    # batched のまま残り、どのバッチにも入っていない宙ぶらりんになる。
    #
    # 状態更新と台帳登録は1トランザクションにする。片方だけ通ると、
    # 「batched だがどのバッチにも属さない」または「台帳にあるが投稿は pending」
    # という状態が生まれる。後者は次の prepare が同じ投稿を別バッチへ載せるため、
    # 同じ投稿を2回抽出することになる。
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.executemany(
            "UPDATE posts SET extraction_status = 'batched' WHERE id = ?",
            [[pid] for pid in post_ids],
        )
        conn.execute(
            """
            INSERT INTO extraction_batches (batch_id, created_at, post_count, extractor_version)
            VALUES (?, ?, ?, ?)
            """,
            [batch_id, now.replace(tzinfo=None), len(records), version],
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return PrepareResult(
        batch_id=batch_id,
        post_count=len(records),
        batch_path=batch_path,
        instruction_path=instruction_path,
    )
