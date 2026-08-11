from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from sns_collector.adapter.db import (
    connect,
    current_version,
    insert_records,
    known_ids,
    latest_version,
    record_keyword_hits,
)
from sns_collector.adapter.db.repository import load_all, load_platform
from tests.conftest import BLUESKY_RECORD


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


@pytest.fixture
def conn(tmp_path: Path):
    with connect(tmp_path / "analysis.duckdb") as c:
        yield c


def test_スキーマは最新まで適用される(conn):
    assert current_version(conn) == latest_version()
    assert conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 0


def test_マイグレーションは何度実行しても増えない(tmp_path: Path):
    db_path = tmp_path / "analysis.duckdb"
    with connect(db_path) as c:
        first = c.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    with connect(db_path) as c:
        second = c.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    assert first == second


def test_同一ファイルを2回ロードしても件数が変わらない(conn, tmp_path: Path):
    """冪等性の担保（F-01）。"""
    data_dir = tmp_path / "data"
    _write_jsonl(data_dir / "bluesky" / "2026-08-02.jsonl", [BLUESKY_RECORD])

    first = load_platform(conn, data_dir, "bluesky")
    assert (first.inserted, first.updated) == (1, 0)

    second = load_platform(conn, data_dir, "bluesky")
    assert (second.inserted, second.updated) == (0, 1)

    assert conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 1


def test_同じ投稿が別キーワードで来たらキーワードを足す(conn, tmp_path: Path):
    data_dir = tmp_path / "data"
    _write_jsonl(
        data_dir / "bluesky" / "2026-08-02.jsonl",
        [BLUESKY_RECORD, {**BLUESKY_RECORD, "keyword": "別のキーワード"}],
    )

    load_platform(conn, data_dir, "bluesky")

    keywords = conn.execute("SELECT matched_keywords FROM posts").fetchone()[0]
    assert sorted(keywords) == ["ラズパイ YOLO", "別のキーワード"]
    assert conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 1


def test_壊れた行だけを捨てて残りを取り込む(conn, tmp_path: Path):
    """1行の破損でそのファイルの残り全部を失わない（design.md §5.5）。"""
    data_dir = tmp_path / "data"
    path = data_dir / "bluesky" / "2026-08-02.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    other = {**BLUESKY_RECORD, "post_id": "at://did:plc:abc/app.bsky.feed.post/other"}
    path.write_text(
        json.dumps(BLUESKY_RECORD, ensure_ascii=False)
        + "\n"
        + "{壊れたJSON\n"
        + json.dumps({"keyword": "post_idが無い"}, ensure_ascii=False)
        + "\n"
        + json.dumps(other, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    result = load_platform(conn, data_dir, "bluesky")

    assert result.skipped == 2
    assert result.inserted == 2, "壊れた行以外の2件が入っていない"


def test_空行があっても壊れた行として数えない(conn, tmp_path: Path):
    data_dir = tmp_path / "data"
    path = data_dir / "bluesky" / "2026-08-02.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n" + json.dumps(BLUESKY_RECORD, ensure_ascii=False) + "\n\n", encoding="utf-8"
    )

    result = load_platform(conn, data_dir, "bluesky")
    assert (result.inserted, result.skipped) == (1, 0)


def test_sinceで収集日より前のファイルを外す(conn, tmp_path: Path):
    data_dir = tmp_path / "data"
    old = {**BLUESKY_RECORD, "post_id": "at://did:plc:abc/app.bsky.feed.post/old"}
    _write_jsonl(data_dir / "bluesky" / "2026-07-01.jsonl", [old])
    _write_jsonl(data_dir / "bluesky" / "2026-08-02.jsonl", [BLUESKY_RECORD])

    result = load_platform(conn, data_dir, "bluesky", since=date(2026, 8, 1))

    assert result.files == 1
    assert result.inserted == 1
    ids = [row[0] for row in conn.execute("SELECT native_id FROM posts").fetchall()]
    assert ids == [BLUESKY_RECORD["post_id"]]


def test_プラットフォームのディレクトリが無くても落ちない(conn, tmp_path: Path):
    results = load_all(conn, tmp_path / "data")
    assert results["bluesky"].files == 0
    assert results["youtube"].files == 0


def test_収集経路とロード経路で二重に入らない(conn, tmp_path: Path):
    """収集時のDB投入とロードは同じアダプタ・同じSQLを通る。

    ここが分かれると、`db load` による再構築（F-04）が収集時と食い違う。
    """
    data_dir = tmp_path / "data"
    _write_jsonl(data_dir / "bluesky" / "2026-08-02.jsonl", [BLUESKY_RECORD])

    insert_records(conn, "bluesky", [BLUESKY_RECORD])
    load_platform(conn, data_dir, "bluesky")

    assert conn.execute("SELECT count(*) FROM posts").fetchone()[0] == 1


def test_known_idsはプラットフォームで絞る(conn):
    insert_records(conn, "bluesky", [BLUESKY_RECORD])

    assert known_ids(conn, "bluesky") == {BLUESKY_RECORD["post_id"]}
    assert known_ids(conn, "youtube") == set()


def test_機械のTZが変わってもDBの値は変わらない(conn, tmp_path: Path):
    """同じJSONLからは同じDBができること（F-04）。"""
    data_dir = tmp_path / "data"
    _write_jsonl(
        data_dir / "bluesky" / "2026-08-02.jsonl",
        [{**BLUESKY_RECORD, "created_at": "2026-06-05T11:47:05+09:00"}],
    )
    load_platform(conn, data_dir, "bluesky")

    stored = conn.execute("SELECT posted_at FROM posts").fetchone()[0]
    assert stored.isoformat() == "2026-06-05T02:47:05"


def test_再ロードで既存行の正規化結果を修復する(conn, tmp_path: Path):
    """アダプタを直した後、過去分に反映できること（F-04）。

    matched_keywords だけを更新する形だと、誤った値のまま入った行を
    二度と直せない。
    """
    data_dir = tmp_path / "data"
    path = data_dir / "bluesky" / "2026-08-02.jsonl"
    _write_jsonl(path, [{**BLUESKY_RECORD, "text": "古い本文"}])
    load_platform(conn, data_dir, "bluesky")

    _write_jsonl(path, [{**BLUESKY_RECORD, "text": "直した本文"}])
    load_platform(conn, data_dir, "bluesky")

    assert conn.execute("SELECT text FROM posts").fetchone()[0] == "直した本文"


def test_再ロードしても抽出状態は戻さない(conn, tmp_path: Path):
    """extraction_status はDB側の状態。上書きすると二重に抽出される。"""
    data_dir = tmp_path / "data"
    _write_jsonl(data_dir / "bluesky" / "2026-08-02.jsonl", [BLUESKY_RECORD])
    load_platform(conn, data_dir, "bluesky")
    conn.execute("UPDATE posts SET extraction_status = 'done'")

    load_platform(conn, data_dir, "bluesky")

    assert conn.execute("SELECT extraction_status FROM posts").fetchone()[0] == "done"


def test_投入に失敗した件数を返す(conn):
    """握り潰すと、その投稿はJSONLに在るのにDBに無く、永久に再収集される。"""
    result = insert_records(conn, "bluesky", [BLUESKY_RECORD, {"keyword": "post_idが無い"}])

    assert result.inserted == 1
    assert result.failed == 1


def test_既知の投稿に別キーワードのヒットを足せる(conn):
    insert_records(conn, "bluesky", [BLUESKY_RECORD])

    record_keyword_hits(conn, "bluesky", [BLUESKY_RECORD["post_id"]], "別のキーワード")

    keywords = conn.execute("SELECT matched_keywords FROM posts").fetchone()[0]
    assert sorted(keywords) == ["ラズパイ YOLO", "別のキーワード"]


def test_同じキーワードを重ねても増えない(conn):
    insert_records(conn, "bluesky", [BLUESKY_RECORD])

    record_keyword_hits(conn, "bluesky", [BLUESKY_RECORD["post_id"]], "ラズパイ YOLO")

    assert conn.execute("SELECT matched_keywords FROM posts").fetchone()[0] == ["ラズパイ YOLO"]


def test_読めないファイルがあっても他のファイルは取り込む(conn, tmp_path: Path):
    """db load は壊れたDBを作り直す経路。ここで全体が止まると復旧手段を失う。"""
    data_dir = tmp_path / "data"
    _write_jsonl(data_dir / "bluesky" / "2026-08-02.jsonl", [BLUESKY_RECORD])
    broken = data_dir / "bluesky" / "2026-08-01.jsonl"
    broken.write_bytes(b"\xff\xfe not utf-8 \x00\n")

    result = load_platform(conn, data_dir, "bluesky")

    assert result.inserted == 1, "壊れたファイル以外が取り込まれていない"
    assert result.skipped == 1
