"""抽出バッチの書き出し（F-07）。

`extraction_status='pending'` の投稿を取り出し、抽出対象のJSONLと
Claude Codeセッションへの作業指示Markdownを書く。

パイプラインからLLMを呼ばない（ADR-0003）。ここはファイルを書くだけで、
推論は人が開いたセッションが行う。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ..jsonl import write_jsonl

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# このファイルから sns-collector/ まで5階層。層構造の深さに依存するため、
# ディレクトリを動かしたらここも直す（テストが FileNotFoundError で気づく）
PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


@dataclass(frozen=True)
class PrepareResult:
    batch_id: str
    post_count: int
    batch_path: Path
    instruction_path: Path


def _batch_id(conn: duckdb.DuckDBPyConnection, now: datetime) -> tuple[str, datetime]:
    """未使用の batch_id を返す。

    IDは秒までしか持たない（design.md §3.4 の書式）。同じ秒に2回 prepare すると
    主キー衝突で落ちるため、空いている秒まで進める。書式を変えないのは、
    IDから作成時刻が読めることを保ちたいため。
    """
    while True:
        candidate = f"batch-{now:%Y%m%d-%H%M%S}"
        exists = conn.execute(
            "SELECT 1 FROM extraction_batches WHERE batch_id = ?", [candidate]
        ).fetchone()
        if exists is None:
            return candidate, now
        now = now + timedelta(seconds=1)


def prompt_path(version: str, prompts_dir: Path | None = None) -> Path:
    return (prompts_dir or PROMPTS_DIR) / f"extract-{version}.md"


# 抽出の既定はBluesky・Hacker Newsの需要シグナル系だけ。
#
# YouTubeは供給シグナル（既存ソリューション・競合・市場の関心度）であり、
# 検索できるのは動画のメタデータに限られる（design.md §4.1）。そこへ
# 「未充足ニーズ／不満」の抽出を掛けても構造的にほぼ none にしかならない。
# 実測: 最初のバッチ20件のうち18件がYouTubeの製品デモで、全件 none だった。
# 供給側の分析はPhase 4のレポートで別途行う。
#
# Hacker Newsはコメント・Ask HN投稿という生の本文が取れる点でBlueskyと同種
# であり、既定に含める（ADR-0006）。
#
# GitHub / Redditは追加したが既定には含めない（ADR-0009）。抽出の歩留まりを
# 実測してから判断する。GitHubのIssue本文はBlueskyの投稿より1〜2桁長く、
# 未検証のまま既定バッチへ混ぜると課金される抽出セッションのコンテキストを
# 圧迫しうる。
DEFAULT_PLATFORMS = ("bluesky", "hackernews")


def _read_template(version: str, prompts_dir: Path | None = None) -> str:
    path = prompt_path(version, prompts_dir)
    if not path.exists():
        base = prompts_dir or PROMPTS_DIR
        available = sorted(p.stem.removeprefix("extract-") for p in base.glob("extract-*.md"))
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


def reopen_for_reextraction(
    conn: duckdb.DuckDBPyConnection,
    version: str,
    platforms: tuple[str, ...] | list[str],
) -> int:
    """指定した版で抽出した投稿のうち、対象プラットフォームのものを pending へ戻す。

    戻した件数を返す。プロンプトを改訂したとき、旧版の結果を新版で取り直すための
    経路（design.md §4.3 再抽出）。`insights` の行は消さない。新版で取り込んだ
    ときに上書きされるため、途中で中断しても旧版の結果が残る。

    **対象は done に限る。** 状態を問わず戻すと、まだ取り込んでいないバッチの
    投稿（batched）まで引き抜かれ、同じ投稿が2つのバッチに載る。再抽出は
    「バッチ作成 → 抽出 → 取り込み」の繰り返しなので、取り込む前にもう一度
    実行する状況は現実に起きる。

    **プラットフォームで絞る。** 選択側（後段のクエリ）は `platforms` に無い
    投稿を拾わない。ここで絞らずに全プラットフォームを戻すと、選択に乗らない
    プラットフォームの投稿が pending のまま孤立する。既定が Bluesky のみの
    ため、`--reextract v1` を素朴に実行すると YouTube の該当投稿が
    巻き添えで戻り、二度と拾われない状態で残っていた（実測18件）。
    """
    placeholders = ", ".join("?" for _ in platforms)
    # 実際に状態が変わる件数を先に数える。`insights` の行数を返すと、
    # 既に pending だったものまで「戻した」ことになって嘘になる
    reopened = conn.execute(
        f"""
        SELECT count(*) FROM posts
        WHERE extraction_status = 'done'
          AND platform IN ({placeholders})
          AND id IN (SELECT post_id FROM insights WHERE extractor_version = ?)
        """,
        [*platforms, version],
    ).fetchone()[0]
    conn.execute(
        f"""
        UPDATE posts SET extraction_status = 'pending'
        WHERE extraction_status = 'done'
          AND platform IN ({placeholders})
          AND id IN (SELECT post_id FROM insights WHERE extractor_version = ?)
        """,
        [*platforms, version],
    )
    return reopened


def prepare(
    conn: duckdb.DuckDBPyConnection,
    extract_dir: Path,
    *,
    limit: int,
    version: str,
    domain_ids: list[str],
    platforms: tuple[str, ...] | list[str] = DEFAULT_PLATFORMS,
    reextract: str | None = None,
    now: datetime | None = None,
    prompts_dir: Path | None = None,
) -> PrepareResult | None:
    """未抽出の投稿をバッチへ書き出す。対象が無ければ None。

    `prompts_dir` は既定で `PROMPTS_DIR`（sns-collector/prompts）。同じパッケージを
    別トピックのconfig/dataへ向けて再利用するインスタンス（例: maritime-collector/）が
    自分のプロンプトを読ませるための上書き先。
    """
    if not platforms:
        raise ValueError("platforms を1つ以上指定する")

    # テンプレートの読み込みを先に済ませる。ファイルを書いた後で失敗すると、
    # どのバッチにも属さないJSONLが extract/ に残る
    template = _read_template(version, prompts_dir)

    now = now or datetime.now(UTC)
    batch_id, now = _batch_id(conn, now)

    # 本文の無い投稿を落とすのはバッチの有無と無関係に正しいので、
    # トランザクションの外で先に済ませる
    skip_unextractable(conn)

    # 再抽出はここから。バッチが作られなかったときに巻き戻したいため、
    # 状態を戻す操作をバッチ作成と同じトランザクションに入れる。
    # 外に置くと「戻り値は None なのに done が pending へ戻る」という、
    # 呼び出し側から追跡できない副作用になる
    conn.execute("BEGIN TRANSACTION")
    try:
        return _prepare_in_transaction(
            conn,
            extract_dir,
            limit=limit,
            version=version,
            template=template,
            domain_ids=domain_ids,
            platforms=platforms,
            reextract=reextract,
            batch_id=batch_id,
            now=now,
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _prepare_in_transaction(
    conn: duckdb.DuckDBPyConnection,
    extract_dir: Path,
    *,
    limit: int,
    version: str,
    template: str,
    domain_ids: list[str],
    platforms: tuple[str, ...] | list[str],
    reextract: str | None,
    batch_id: str,
    now: datetime,
) -> PrepareResult | None:
    if reextract:
        reopen_for_reextraction(conn, reextract, platforms)

    # 新しく収集したものから出す。
    # 投稿日の古い順にすると、初回収集で遡った過去分（最古は2009年）から処理する
    # ことになり、現在のキーワード設計と対応しない投稿にセッション時間を使う。
    # 収集日で並べれば、いま効いているキーワードが拾ったものから順に見られる。
    placeholders = ", ".join("?" for _ in platforms)
    params: list[str | int] = [*platforms]

    # 再抽出を指定したら、その版で抽出した投稿だけを対象にする。
    # 戻すだけだと未抽出の投稿と同じ土俵に並び、収集日順では新しいものに
    # 押し出される。実測では20件中12件しか再抽出対象が入らなかった。
    # 「この版を取り直す」という指定が、取り直しにならない。
    reextract_filter = ""
    if reextract:
        reextract_filter = "AND id IN (SELECT post_id FROM insights WHERE extractor_version = ?)"
        params.append(reextract)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, platform, text, posted_at, matched_keywords
        FROM posts
        WHERE extraction_status = 'pending'
          AND platform IN ({placeholders})
          AND text IS NOT NULL AND length(trim(text)) > 0
          {reextract_filter}
        ORDER BY collected_at DESC NULLS LAST, id
        LIMIT ?
        """,
        params,
    ).fetchall()

    if not rows:
        # 再抽出で戻した状態もここで巻き戻る
        conn.execute("ROLLBACK")
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
    # 状態更新と台帳登録が片方だけ通ると、「batched だがどのバッチにも属さない」
    # または「台帳にあるが投稿は pending」という状態が生まれる。後者は次の
    # prepare が同じ投稿を別バッチへ載せるため、同じ投稿を2回抽出することになる。
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

    return PrepareResult(
        batch_id=batch_id,
        post_count=len(records),
        batch_path=batch_path,
        instruction_path=instruction_path,
    )
