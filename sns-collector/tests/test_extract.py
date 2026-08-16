from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sns_collector.adapter.db import connect, insert_records
from sns_collector.adapter.db.extract_load import load, status
from sns_collector.adapter.db.extract_prepare import (
    DEFAULT_PLATFORMS,
    prepare,
    reopen_for_reextraction,
)
from sns_collector.domain.config import Domain
from sns_collector.domain.insight import ValidationError, validate
from tests.conftest import BLUESKY_RECORD, YOUTUBE_RECORD


def test_抽出の既定対象にgithubとredditを含めない():
    """実測前に既定へ入れない(ADR-0009)。歩留まりを測ってから判断する。"""
    assert DEFAULT_PLATFORMS == ("bluesky", "hackernews")


DOMAINS = frozenset({"ai_accuracy", "edge_ai", "fabrication", "other"})


def _domains() -> list[Domain]:
    """統制語彙。prepare は id だけでなく label / boundary も受け取る
    （抽出プロンプトへ境界を渡すため。ADR-0011以降の domains.yaml）。"""
    return [Domain(id=d, label=d) for d in sorted(DOMAINS)]


VALID = {
    "post_id": "bluesky:at://did:plc:abc/app.bsky.feed.post/xyz",
    "insight_type": "complaint",
    "domain": "edge_ai",
    "summary": "ラズパイでの推論が遅く、実用にならないという不満",
    "pain_level": 2,
    "monetizable": False,
    "competitors": ["Ollama"],
    "confidence": 0.8,
}


def _valid(**over) -> dict:
    return {**VALID, **over}


# ── スキーマ検証（正常系） ──────────────────────────────────────────────


def test_正常な行はInsightになる():
    i = validate(VALID, allowed_domains=DOMAINS)
    assert i.insight_type == "complaint"
    assert i.competitors == ["Ollama"]


def test_noneはdomainとsummaryを持たない():
    """洞察が無い投稿も記録して再抽出を防ぐ（design.md §3.2）。"""
    i = validate(
        _valid(insight_type="none", domain="edge_ai", summary="無視される", pain_level=0),
        allowed_domains=DOMAINS,
    )
    assert i.domain is None
    assert i.summary is None


# ── スキーマ違反 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("over", "理由"),
    [
        ({"insight_type": "unknown"}, "語彙外のinsight_type"),
        ({"domain": "存在しない領域"}, "統制語彙外のdomain"),
        ({"pain_level": 4}, "pain_levelが範囲外"),
        ({"pain_level": -1}, "pain_levelが範囲外(負)"),
        ({"pain_level": "2"}, "pain_levelが文字列"),
        ({"confidence": 1.5}, "confidenceが範囲外"),
        ({"monetizable": "yes"}, "monetizableが真偽値でない"),
        ({"competitors": "Ollama"}, "competitorsが配列でない"),
        ({"summary": ""}, "summaryが空"),
        ({"post_id": ""}, "post_idが空"),
        ({"insight_type": "none", "pain_level": 2}, "noneなのにpain_levelが0でない"),
    ],
)
def test_スキーマ違反は拒否する(over, 理由):
    with pytest.raises(ValidationError):
        validate(_valid(**over), allowed_domains=DOMAINS)


def test_真偽値をpain_levelに使えない():
    """boolはintの派生。通すと型の取り違えを見逃す。"""
    with pytest.raises(ValidationError):
        validate(_valid(pain_level=True), allowed_domains=DOMAINS)


def test_summaryが長すぎれば拒否する():
    with pytest.raises(ValidationError):
        validate(_valid(summary="あ" * 401), allowed_domains=DOMAINS)


# ── prepare / load の往復 ───────────────────────────────────────────────


@pytest.fixture
def prepared(tmp_path: Path):
    """1件の投稿を入れてバッチを作った状態。"""
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        result = prepare(
            conn,
            tmp_path / "extract",
            limit=10,
            version="v1",
            domains=_domains(),
            now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        )
        yield conn, tmp_path / "extract", result


def _write_result(extract_dir: Path, batch_id: str, records: list[dict]) -> None:
    (extract_dir / f"{batch_id}.result.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def test_prepareはバッチと作業指示を書き状態を進める(prepared):
    conn, extract_dir, result = prepared

    assert result is not None
    assert result.post_count == 1
    assert result.batch_path.exists()
    assert result.instruction_path.exists()

    instruction = result.instruction_path.read_text(encoding="utf-8")
    assert "{batch_jsonl}" not in instruction, "テンプレートの差し込みが済んでいない"
    assert str(result.batch_path) in instruction
    assert "edge_ai" in instruction, "統制語彙が作業指示に入っていない"

    assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "batched"


def test_prepareは対象が無ければNoneを返す(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        assert (
            prepare(
                conn,
                tmp_path / "extract",
                limit=10,
                version="v1",
                domains=[Domain(id="other", label="other")],
            )
            is None
        )


def test_batchedの投稿は次のバッチに入らない(prepared):
    """二重にバッチへ載せると、同じ投稿を2回抽出することになる。"""
    conn, extract_dir, _ = prepared
    assert (
        prepare(
            conn, extract_dir, limit=10, version="v1", domains=[Domain(id="other", label="other")]
        )
        is None
    )


def test_loadは検証を通った行だけ入れる(prepared):
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid()])

    r = load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    assert (r.accepted, r.rejected) == (1, 0)
    assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "done"
    row = conn.execute("SELECT insight_type, extractor_version FROM insights").fetchone()
    assert row == ("complaint", "v1")


def test_バッチに無いpost_idは拒否する(prepared):
    """ハルシネーション検出。通すと存在しない投稿の洞察がDBに入る。"""
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid(post_id="bluesky:at://存在しない")])

    r = load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    assert (r.accepted, r.rejected) == (0, 1)
    assert conn.execute("SELECT count(*) FROM insights").fetchone()[0] == 0
    assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "batched"


def test_重複したpost_idは2件目を拒否する(prepared):
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid(), _valid(pain_level=3)])

    r = load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    assert (r.accepted, r.rejected) == (1, 1)
    assert conn.execute("SELECT pain_level FROM insights").fetchone()[0] == 2, "先勝ち"


def test_拒否した行はerrorsファイルへ隔離する(prepared):
    conn, extract_dir, result = prepared
    (extract_dir / f"{result.batch_id}.result.jsonl").write_text(
        json.dumps(_valid(pain_level=9), ensure_ascii=False) + "\n{壊れたJSON\n", encoding="utf-8"
    )

    r = load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    assert r.rejected == 2
    assert r.errors_path is not None and r.errors_path.exists()
    reasons = [json.loads(x)["reason"] for x in r.errors_path.read_text().splitlines()]
    assert any("pain_level" in x for x in reasons)
    assert any("JSON" in x for x in reasons)


def test_全件拒否でもバッチは取り込み済みになる(prepared):
    """未取り込み扱いのまま残すと、status の未取り込み一覧が永久に消えない。"""
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid(pain_level=9)])

    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    assert status(conn)["unloaded_batches"] == []


def test_再取り込みで洞察を上書きする(prepared):
    """extractor_version を上げた後の入れ直し（design.md §4.3 再抽出）。"""
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid()])
    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    _write_result(extract_dir, result.batch_id, [_valid(pain_level=3, summary="直した要約")])
    r = load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    assert r.accepted == 1
    assert conn.execute("SELECT count(*) FROM insights").fetchone()[0] == 1
    assert conn.execute("SELECT pain_level FROM insights").fetchone()[0] == 3


def test_要約が変わったら埋め込みを捨てる(prepared):
    """embed は embedding IS NULL しか拾わない。ここで消さないと古いベクトルが残り続ける。"""
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid(summary="元の要約")])
    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)
    conn.execute("UPDATE insights SET embedding = [1.0, 2.0], embedding_model = 'model-a'")

    _write_result(extract_dir, result.batch_id, [_valid(summary="直した要約")])
    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    row = conn.execute("SELECT embedding, embedding_model FROM insights").fetchone()
    assert row == (None, None)


def test_要約が同じなら埋め込みを残す(prepared):
    """誤検知しないこと。再取り込みのたびに再埋め込みさせない。"""
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid(summary="同じ要約")])
    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)
    conn.execute("UPDATE insights SET embedding = [1.0, 2.0], embedding_model = 'model-a'")

    _write_result(extract_dir, result.batch_id, [_valid(summary="同じ要約", pain_level=3)])
    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    row = conn.execute("SELECT embedding, embedding_model, pain_level FROM insights").fetchone()
    assert row == ([1.0, 2.0], "model-a", 3)


def test_未登録のバッチは拒否する(prepared):
    conn, extract_dir, _ = prepared
    (extract_dir / "batch-99999999-000000.jsonl").write_text("", encoding="utf-8")
    _write_result(extract_dir, "batch-99999999-000000", [])

    with pytest.raises(ValueError, match="未登録のバッチ"):
        load(conn, extract_dir, "batch-99999999-000000", allowed_domains=DOMAINS)


def test_statusは待ち件数と未取り込みを返す(prepared):
    conn, _, result = prepared
    st = status(conn)

    assert st["posts"] == {"batched": 1}
    assert [b[0] for b in st["unloaded_batches"]] == [result.batch_id]


# ── バッチ選択（実測で判明した2つの問題への回帰テスト） ──────────────────


def _post(pid: str, platform: str, collected: str, posted: str) -> dict:
    if platform == "bluesky":
        return {
            **BLUESKY_RECORD,
            "post_id": pid,
            "collected_at": collected,
            "created_at": posted,
        }
    return {
        "video_id": pid,
        "keyword": "Jetson YOLO",
        "title": "製品デモ",
        "description": "",
        "channel_id": "UC1",
        "channel_title": "ch",
        "published_at": posted,
        "url": "https://example/v",
        "collected_at": collected,
    }


def test_既定ではYouTubeをバッチに載せない(tmp_path: Path):
    """YouTubeは供給シグナル。需要シグナルの抽出を掛けても none にしかならない。

    最初のバッチ20件のうち18件がYouTubeの製品デモで、全件 none だった。
    """
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(
            conn,
            "youtube",
            [_post("v1", "youtube", "2026-08-04T00:00:00+00:00", "2016-01-01T00:00:00Z")],
        )
        insert_records(
            conn,
            "bluesky",
            [_post("b1", "bluesky", "2026-08-04T00:00:00+00:00", "2026-08-01T00:00:00Z")],
        )

        result = prepare(conn, tmp_path / "extract", limit=10, version="v1", domains=_domains())

        assert result.post_count == 1
        ids = [json.loads(x)["id"] for x in result.batch_path.read_text().splitlines()]
        assert ids == ["bluesky:b1"]


def test_platform指定でYouTubeも載せられる(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(
            conn,
            "youtube",
            [_post("v1", "youtube", "2026-08-04T00:00:00+00:00", "2016-01-01T00:00:00Z")],
        )

        result = prepare(
            conn,
            tmp_path / "extract",
            limit=10,
            version="v1",
            domains=_domains(),
            platforms=("youtube",),
        )

        assert result.post_count == 1


def test_新しく収集したものから出す(tmp_path: Path):
    """投稿日の古い順にすると、2009年まで遡った過去分から処理することになる。

    現在のキーワード設計と対応しない投稿にセッション時間を使ってしまう。
    """
    with connect(tmp_path / "analysis.duckdb") as conn:
        # 投稿日は新しいが収集は古い / 投稿日は古いが収集は新しい
        insert_records(
            conn,
            "bluesky",
            [
                _post(
                    "old_collect", "bluesky", "2026-07-01T00:00:00+00:00", "2026-06-30T00:00:00Z"
                ),
                _post(
                    "new_collect", "bluesky", "2026-08-04T00:00:00+00:00", "2009-01-01T00:00:00Z"
                ),
            ],
        )

        result = prepare(conn, tmp_path / "extract", limit=1, version="v1", domains=_domains())

        ids = [json.loads(x)["id"] for x in result.batch_path.read_text().splitlines()]
        assert ids == ["bluesky:new_collect"], "収集が新しいものが先に来ていない"


# ── レビュー指摘への回帰テスト ──────────────────────────────────────────


def test_本文の無い投稿はskippedへ落とす(tmp_path: Path):
    """pending に残すと、どのバッチにも載らないのに待ち件数へ数え続けられる。

    実データで57件あり、待ち件数が実態とずれて進捗を判断できなくなっていた。
    """
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(
            conn,
            "bluesky",
            [
                {**BLUESKY_RECORD, "post_id": "empty", "text": "   "},
                {**BLUESKY_RECORD, "post_id": "ok"},
            ],
        )

        prepare(conn, tmp_path / "extract", limit=10, version="v1", domains=_domains())

        assert status(conn)["posts"] == {"batched": 1, "skipped": 1}


def test_本文が無い投稿しか無ければバッチを作らない(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [{**BLUESKY_RECORD, "post_id": "empty", "text": ""}])

        assert (
            prepare(
                conn,
                tmp_path / "extract",
                limit=10,
                version="v1",
                domains=[Domain(id="other", label="other")],
            )
            is None
        )
        assert status(conn)["posts"] == {"skipped": 1}


def test_prompts_dirを指定すると別ディレクトリのプロンプトを読む(tmp_path: Path):
    """同じパッケージを別トピックのconfig/dataへ向けて再利用するインスタンス用。"""
    prompts_dir = tmp_path / "custom_prompts"
    prompts_dir.mkdir()
    (prompts_dir / "extract-v1.md").write_text(
        "カスタム指示 {batch_jsonl} {result_jsonl} {domain_ids}", encoding="utf-8"
    )
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        result = prepare(
            conn,
            extract_dir,
            limit=10,
            version="v1",
            domains=[Domain(id="other", label="other")],
            prompts_dir=prompts_dir,
        )

    assert result is not None
    instruction = result.instruction_path.read_text(encoding="utf-8")
    assert instruction.startswith("カスタム指示 ")


def test_prompts_dir未指定なら既定のsns_collectorプロンプトを読む(prepared):
    """既存の呼び出し(prompts_dirを渡さない)が今までと同じ動作を保つことの確認。"""
    conn, extract_dir, result = prepared

    assert result is not None
    instruction = result.instruction_path.read_text(encoding="utf-8")
    assert "抽出指示" in instruction, "sns-collector/prompts/extract-v1.mdの内容が読めていない"


def test_存在しないプロンプト版ではファイルを1つも書かない(tmp_path: Path):
    """ファイルを書いた後で失敗すると、どのバッチにも属さないJSONLが残る。"""
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])

        with pytest.raises(FileNotFoundError, match="利用できる版"):
            prepare(
                conn,
                extract_dir,
                limit=10,
                version="v99",
                domains=[Domain(id="other", label="other")],
            )

        assert not extract_dir.exists() or list(extract_dir.iterdir()) == []
        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "pending"


class _FailOnBatchInsert:
    """extraction_batches への INSERT だけを失敗させる薄いプロキシ。

    バッチIDの衝突では失敗させられなくなったため（空き秒まで進めるようにした）、
    ロールバックの検証にはこの形が要る。
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args, **kwargs):
        if "INSERT INTO extraction_batches" in sql:
            raise RuntimeError("台帳の登録に失敗した")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_台帳登録が失敗したら投稿の状態も戻す(tmp_path: Path):
    """片方だけ通ると、次の prepare が同じ投稿を別バッチへ載せて二重抽出になる。"""
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])

        with pytest.raises(RuntimeError, match="台帳の登録"):
            prepare(
                _FailOnBatchInsert(conn),
                tmp_path / "extract",
                limit=10,
                version="v2",
                domains=[Domain(id="other", label="other")],
            )

        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "pending", (
            "台帳が入らなかったのに投稿だけ batched になっている"
        )
        assert conn.execute("SELECT count(*) FROM extraction_batches").fetchone()[0] == 0


def test_platformsが空なら早期に拒否する(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        with pytest.raises(ValueError, match="platforms"):
            prepare(
                conn,
                tmp_path / "extract",
                limit=10,
                version="v1",
                domains=[Domain(id="other", label="other")],
                platforms=(),
            )


def test_reextractで旧版の投稿をpendingへ戻す(tmp_path: Path):
    """プロンプト改訂後に旧版の結果を取り直す経路（design.md §4.3）。"""
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        first = prepare(conn, extract_dir, limit=10, version="v1", domains=_domains())
        _write_result(extract_dir, first.batch_id, [_valid()])
        load(conn, extract_dir, first.batch_id, allowed_domains=DOMAINS)
        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "done"

        second = prepare(
            conn, extract_dir, limit=10, version="v2", domains=_domains(), reextract="v1"
        )

        assert second is not None, "v1で抽出済みの投稿が再バッチに載っていない"
        assert conn.execute("SELECT count(*) FROM insights").fetchone()[0] == 1, (
            "旧版の結果を消してはならない。新版の取り込みで上書きされる"
        )


def test_該当しない版を指定しても既存の状態を壊さない(tmp_path: Path):
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        prepare(conn, extract_dir, limit=10, version="v2", domains=_domains())

        assert (
            prepare(
                conn,
                extract_dir,
                limit=10,
                version="v2",
                domains=[Domain(id="other", label="other")],
                reextract="v99",
            )
            is None
        )
        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "batched"


def test_同じ秒に2回prepareしても衝突しない(tmp_path: Path):
    """batch_id は秒までしか持たない（design.md §3.4）。空いている秒まで進める。"""
    fixed = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(
            conn,
            "bluesky",
            [{**BLUESKY_RECORD, "post_id": f"p{i}"} for i in range(2)],
        )

        a = prepare(
            conn,
            tmp_path / "extract",
            limit=1,
            version="v2",
            domains=[Domain(id="other", label="other")],
            now=fixed,
        )
        b = prepare(
            conn,
            tmp_path / "extract",
            limit=1,
            version="v2",
            domains=[Domain(id="other", label="other")],
            now=fixed,
        )

        assert a.batch_id != b.batch_id
        assert b.batch_id == "batch-20260805-120001"


def test_バッチが作られなければ再抽出の状態変更も巻き戻す(tmp_path: Path):
    """戻り値が None なのに done が pending へ戻ると、呼び出し側から追跡できない。

    `--reextract v1 --platform youtube` のように、戻した投稿が選択条件に
    合致しない組み合わせで踏む。
    """
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        first = prepare(conn, extract_dir, limit=10, version="v1", domains=_domains())
        _write_result(extract_dir, first.batch_id, [_valid()])
        load(conn, extract_dir, first.batch_id, allowed_domains=DOMAINS)
        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "done"

        out = prepare(
            conn,
            extract_dir,
            limit=10,
            version="v2",
            domains=_domains(),
            platforms=("youtube",),
            reextract="v1",
        )

        assert out is None
        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "done", (
            "バッチが作られていないのに状態だけ pending へ戻っている"
        )


def test_バッチが作られなくても本文の無い投稿はskippedのまま(tmp_path: Path):
    """本文の無い投稿を落とすのはバッチの有無と無関係に正しい。巻き戻さない。"""
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [{**BLUESKY_RECORD, "post_id": "empty", "text": ""}])

        assert (
            prepare(
                conn,
                tmp_path / "extract",
                limit=10,
                version="v2",
                domains=[Domain(id="other", label="other")],
            )
            is None
        )
        assert status(conn)["posts"] == {"skipped": 1}


def test_再抽出の戻り値は実際に状態が変わった件数(tmp_path: Path):
    """`insights` の行数を返すと、既に pending だったものまで数えて嘘になる。"""
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        first = prepare(conn, extract_dir, limit=10, version="v1", domains=_domains())
        _write_result(extract_dir, first.batch_id, [_valid()])
        load(conn, extract_dir, first.batch_id, allowed_domains=DOMAINS)

        assert reopen_for_reextraction(conn, "v1", ("bluesky",)) == 1
        assert reopen_for_reextraction(conn, "v1", ("bluesky",)) == 0, (
            "既に pending のものを数えている"
        )


def test_reopen_for_reextractionは対象外プラットフォームを戻さない(tmp_path: Path):
    """プラットフォームで絞らずに戻すと、選択に乗らないプラットフォームの投稿が
    pending のまま孤立する。既定が Bluesky のみのため、`--reextract v1` を
    素朴に実行すると YouTube の投稿が巻き添えで pending へ落ち、
    二度と拾われない状態で残っていた（実測18件、issue #3）。
    """
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        insert_records(conn, "youtube", [YOUTUBE_RECORD])
        first = prepare(
            conn,
            extract_dir,
            limit=10,
            version="v1",
            domains=_domains(),
            platforms=("bluesky", "youtube"),
        )
        _write_result(
            extract_dir,
            first.batch_id,
            [_valid(), _valid(post_id=f"youtube:{YOUTUBE_RECORD['video_id']}")],
        )
        load(conn, extract_dir, first.batch_id, allowed_domains=DOMAINS)

        # 既定は Bluesky のみ。YouTube の done は触られてはならない
        assert reopen_for_reextraction(conn, "v1", ("bluesky",)) == 1
        statuses = dict(conn.execute("SELECT platform, extraction_status FROM posts").fetchall())
        assert statuses["youtube"] == "done", "対象外プラットフォームが pending へ巻き添えになった"
        assert statuses["bluesky"] == "pending"


def test_reextract指定時は対象をその版に限る(tmp_path: Path):
    """戻すだけだと未抽出の投稿と同じ土俵に並び、収集日順で押し出される。

    実測では20件中12件しか再抽出対象が入らず、「取り直す」指定が
    取り直しにならなかった。
    """
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        # v1で抽出済み（収集は古い）と、未抽出（収集は新しい）を混ぜる
        insert_records(
            conn,
            "bluesky",
            [{**BLUESKY_RECORD, "post_id": "old", "collected_at": "2026-08-01T00:00:00+00:00"}],
        )
        first = prepare(conn, extract_dir, limit=10, version="v1", domains=_domains())
        _write_result(extract_dir, first.batch_id, [_valid(post_id="bluesky:old")])
        load(conn, extract_dir, first.batch_id, allowed_domains=DOMAINS)
        insert_records(
            conn,
            "bluesky",
            [{**BLUESKY_RECORD, "post_id": "new", "collected_at": "2026-08-08T00:00:00+00:00"}],
        )

        result = prepare(
            conn, extract_dir, limit=10, version="v2", domains=_domains(), reextract="v1"
        )

        ids = [json.loads(x)["id"] for x in result.batch_path.read_text().splitlines()]
        assert ids == ["bluesky:old"], "再抽出対象以外が混ざっている"


def test_未取り込みバッチの投稿は再抽出で引き抜かない(tmp_path: Path):
    """状態を問わず戻すと、同じ投稿が2つのバッチに載る。

    再抽出は「バッチ作成 → 抽出 → 取り込み」の繰り返しなので、
    取り込む前にもう一度実行する状況は現実に起きる。
    """
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        first = prepare(
            conn, extract_dir, limit=5, version="v1", domains=[Domain(id="other", label="other")]
        )
        _write_result(extract_dir, first.batch_id, [_valid()])
        load(conn, extract_dir, first.batch_id, allowed_domains=DOMAINS)

        second = prepare(
            conn,
            extract_dir,
            limit=5,
            version="v2",
            domains=[Domain(id="other", label="other")],
            reextract="v1",
        )
        assert second is not None

        # second を取り込まないまま、もう一度 --reextract v1 を叩く
        third = prepare(
            conn,
            extract_dir,
            limit=5,
            version="v2",
            domains=[Domain(id="other", label="other")],
            reextract="v1",
        )

        assert third is None, "未取り込みバッチの投稿が引き抜かれている"
        unloaded = [b[0] for b in status(conn)["unloaded_batches"]]
        assert unloaded == [second.batch_id]


def test_抽出指示にドメインの境界が埋め込まれる(tmp_path: Path):
    """id の羅列だけでは、隣接する語彙を取り違える。

    `edge_ai` と `embedded_dev` の区別は domains.yaml の note（散文）にあるが、
    それは抽出セッションへ渡らない。境界は `boundary` として構造化し、
    プロンプトの `{domain_guide}` へ埋める（issue #71）。
    """
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "extract-v9.md").write_text(
        "選択肢: {domain_ids}\n\n{domain_guide}\n", encoding="utf-8"
    )

    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        result = prepare(
            conn,
            tmp_path / "extract",
            limit=10,
            version="v9",
            domains=[
                Domain(id="edge_ai", label="エッジ推論", boundary="組込み一般は embedded_dev"),
                Domain(id="other", label="該当なし"),
            ],
            prompts_dir=prompts_dir,
        )

    assert result is not None
    text = result.instruction_path.read_text(encoding="utf-8")
    assert "選択肢: edge_ai | other" in text
    assert "- `edge_ai` — エッジ推論。組込み一般は embedded_dev" in text
    assert "- `other` — 該当なし" in text, "boundary が無いドメインも一覧に出す"


def test_取り込みが途中で落ちたら埋め込みも要約も戻す(prepared, monkeypatch):
    """このUPSERTは**データを消す文**である。部分適用を残さない。

    `executemany` は1行ずつオートコミットするため、包まないと先行分だけ
    要約が入れ替わってベクトルが消える。しかも `embedding IS NULL` になった行は
    やり直しても before - after が0になり、破棄の事実がどこにも残らない
    （運用者が embed を回さない限り、その投稿は無言で search から消える）。
    """
    conn, extract_dir, result = prepared
    _write_result(extract_dir, result.batch_id, [_valid(summary="元の要約")])
    load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)
    conn.execute("UPDATE insights SET embedding = [1.0, 2.0], embedding_model = 'model-a'")

    # バッチ更新の直前で落として、UPSERT だけが適用された状態を作る
    import sns_collector.adapter.db.extract_load as mod

    original = mod._write_accepted

    def _boom(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("書き込みの途中で落ちた")

    monkeypatch.setattr(mod, "_write_accepted", _boom)

    _write_result(extract_dir, result.batch_id, [_valid(summary="新しい要約")])
    with pytest.raises(RuntimeError):
        load(conn, extract_dir, result.batch_id, allowed_domains=DOMAINS)

    row = conn.execute("SELECT summary, embedding, embedding_model FROM insights").fetchone()
    assert row[0] == "元の要約", "要約が部分的に入れ替わっている"
    assert row[1] is not None, "ベクトルが消えたまま戻っていない"
    assert row[2] == "model-a"
