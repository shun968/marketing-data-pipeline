from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sns_collector.db import connect, insert_records
from sns_collector.extract import ValidationError, load, prepare, status, validate
from tests.conftest import BLUESKY_RECORD

DOMAINS = frozenset({"ai_accuracy", "edge_ai", "fabrication", "other"})

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
            domain_ids=sorted(DOMAINS),
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
            prepare(conn, tmp_path / "extract", limit=10, version="v1", domain_ids=["other"])
            is None
        )


def test_batchedの投稿は次のバッチに入らない(prepared):
    """二重にバッチへ載せると、同じ投稿を2回抽出することになる。"""
    conn, extract_dir, _ = prepared
    assert prepare(conn, extract_dir, limit=10, version="v1", domain_ids=["other"]) is None


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

        result = prepare(
            conn, tmp_path / "extract", limit=10, version="v1", domain_ids=sorted(DOMAINS)
        )

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
            domain_ids=sorted(DOMAINS),
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

        result = prepare(
            conn, tmp_path / "extract", limit=1, version="v1", domain_ids=sorted(DOMAINS)
        )

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

        prepare(conn, tmp_path / "extract", limit=10, version="v1", domain_ids=sorted(DOMAINS))

        assert status(conn)["posts"] == {"batched": 1, "skipped": 1}


def test_本文が無い投稿しか無ければバッチを作らない(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [{**BLUESKY_RECORD, "post_id": "empty", "text": ""}])

        assert (
            prepare(conn, tmp_path / "extract", limit=10, version="v1", domain_ids=["other"])
            is None
        )
        assert status(conn)["posts"] == {"skipped": 1}


def test_存在しないプロンプト版ではファイルを1つも書かない(tmp_path: Path):
    """ファイルを書いた後で失敗すると、どのバッチにも属さないJSONLが残る。"""
    extract_dir = tmp_path / "extract"
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])

        with pytest.raises(FileNotFoundError, match="利用できる版"):
            prepare(conn, extract_dir, limit=10, version="v99", domain_ids=["other"])

        assert not extract_dir.exists() or list(extract_dir.iterdir()) == []
        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "pending"


def test_台帳登録が失敗したら投稿の状態も戻す(tmp_path: Path):
    """片方だけ通ると、次の prepare が同じ投稿を別バッチへ載せて二重抽出になる。"""
    with connect(tmp_path / "analysis.duckdb") as conn:
        insert_records(conn, "bluesky", [BLUESKY_RECORD])
        fixed = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
        prepare(conn, tmp_path / "extract", limit=10, version="v1", domain_ids=["other"], now=fixed)
        conn.execute("UPDATE posts SET extraction_status = 'pending'")

        # 同じ時刻 = 同じ batch_id。台帳の主キー衝突で INSERT が落ちる
        with pytest.raises(Exception):  # noqa: B017 - duckdbの例外型に依存しない
            prepare(
                conn, tmp_path / "extract", limit=10, version="v1", domain_ids=["other"], now=fixed
            )

        assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "pending", (
            "台帳が入らなかったのに投稿だけ batched になっている"
        )


def test_platformsが空なら早期に拒否する(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as conn:
        with pytest.raises(ValueError, match="platforms"):
            prepare(
                conn,
                tmp_path / "extract",
                limit=10,
                version="v1",
                domain_ids=["other"],
                platforms=(),
            )
