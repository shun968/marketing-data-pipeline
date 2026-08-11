from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from sns_collector.common.config import ConfigError, HackerNewsJobsConfig
from sns_collector.hnjobs import search as hnjobs_search

HIRING_THREAD = {"objectID": "49156683", "title": "Ask HN: Who is hiring? (August 2026)"}
HIRED_THREAD = {"objectID": "49156682", "title": "Ask HN: Who wants to be hired? (August 2026)"}
# 案件スレッドは2026年1月からjon_northが引き継いでいる(2026-08-11 実測)
FREELANCER_THREAD = {
    "objectID": "49157021",
    "title": "Ask HN: Freelancer? Seeking freelancer? (August 2026)",
}
OLD_HIRING_THREAD = {"objectID": "48747976", "title": "Ask HN: Who is hiring? (July 2026)"}

# 主催アカウントごとの投稿。実際のAPIと同じく、1アカウントが複数種別を立てうる
THREADS_BY_AUTHOR = {
    "whoishiring": [HIRING_THREAD, HIRED_THREAD, OLD_HIRING_THREAD],
    "jon_north": [FREELANCER_THREAD],
}

FAKE_HIT = {
    "objectID": "49175131",
    "author": "bzimm",
    "created_at": "2026-08-05T12:00:00Z",
    "parent_id": 49156683,
    "story_id": 49156683,
    "comment_text": "Brightcore Energy | Senior Embedded Engineer | Brooklyn, NY",
}


def _config(
    keywords: list[str],
    thread_kinds: list[str] | None = None,
    thread_limit: int = 4,
) -> HackerNewsJobsConfig:
    return HackerNewsJobsConfig(
        thread_kinds=thread_kinds if thread_kinds is not None else ["hiring", "freelancer"],
        thread_limit=thread_limit,
        hits_per_page=50,
        keywords=keywords,
    )


def _fake_list_threads(author: str, _hits_per_page: int) -> list[dict]:
    return THREADS_BY_AUTHOR.get(author, [])


def test_run_writes_new_entries_and_skips_duplicates(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    for _ in range(2):
        with (
            patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
            patch("sns_collector.hnjobs.search.search_thread", return_value=[FAKE_HIT]),
        ):
            hnjobs_search.run(_config(["embedded"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "2回目の実行で同じ求人が重複して書かれている"
    record = json.loads(lines[0])
    assert record["item_id"] == "49175131"
    assert record["thread_kind"] == "hiring"
    assert record["thread_id"] == "49156683"


def test_freelancer_thread_from_another_host_is_collected(tmp_path: Path):
    """案件スレッドの主催は求人スレッドと別アカウント。取りこぼすと案件が0件になる。

    2026年1月にwhoishiring -> jon_northの引き継ぎが起きている。単一アカウント固定の
    実装だと、この月から案件側だけが静かに収集されなくなる。
    """
    data_dir = tmp_path / "data"
    searched: list[str] = []

    def fake_search(story_id, _keyword, _hits):
        searched.append(story_id)
        return []

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", side_effect=fake_search),
    ):
        hnjobs_search.run(
            _config(["embedded"]), data_dir=data_dir, db_path=tmp_path / "data" / "analysis.duckdb"
        )

    assert FREELANCER_THREAD["objectID"] in searched


def test_replies_are_not_collected_as_job_entries(tmp_path: Path):
    """スレッド直下でないコメントは求人票ではない。採ると議論の断片がDBへ入る。"""
    data_dir = tmp_path / "data"
    reply = {**FAKE_HIT, "objectID": "49175999", "parent_id": 49175131}

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", return_value=[FAKE_HIT, reply]),
    ):
        hnjobs_search.run(
            _config(["embedded"]), data_dir=data_dir, db_path=tmp_path / "data" / "analysis.duckdb"
        )

    lines = list(data_dir.glob("*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["item_id"] == "49175131"


def test_only_configured_thread_kinds_are_collected(tmp_path: Path):
    """求職スレッド(hired)は「金を出す側」ではないため既定で採らない。"""
    data_dir = tmp_path / "data"
    searched: list[str] = []

    def fake_search(story_id, _keyword, _hits):
        searched.append(story_id)
        return []

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", side_effect=fake_search),
    ):
        hnjobs_search.run(
            _config(["embedded"]), data_dir=data_dir, db_path=tmp_path / "data" / "analysis.duckdb"
        )

    assert HIRED_THREAD["objectID"] not in searched


def test_thread_limit_is_counted_per_kind(tmp_path: Path):
    """上限は種別ごとに数える。全体で数えると案件スレッドが枠から溢れる。"""
    data_dir = tmp_path / "data"
    searched: list[str] = []

    def fake_search(story_id, _keyword, _hits):
        searched.append(story_id)
        return []

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", side_effect=fake_search),
    ):
        hnjobs_search.run(
            _config(["embedded"], thread_limit=1),
            data_dir=data_dir,
            db_path=tmp_path / "data" / "analysis.duckdb",
        )

    # 求人1本(新しい方)と案件1本。古い求人スレッドは上限で落ちる
    assert searched == [HIRING_THREAD["objectID"], FREELANCER_THREAD["objectID"]]


def test_unknown_thread_kind_is_rejected_before_collecting(tmp_path: Path):
    """綴り違いを「対象0件」として静かに通すと、収集できていないことに気づけない。"""
    with pytest.raises(ConfigError, match="hirring"):
        hnjobs_search.run(
            _config(["embedded"], thread_kinds=["hirring"]),
            data_dir=tmp_path / "data",
            db_path=tmp_path / "data" / "analysis.duckdb",
        )


def test_empty_thread_kinds_is_rejected(tmp_path: Path):
    with pytest.raises(ConfigError):
        hnjobs_search.run(
            _config(["embedded"], thread_kinds=[]),
            data_dir=tmp_path / "data",
            db_path=tmp_path / "data" / "analysis.duckdb",
        )


def test_failed_pair_does_not_discard_other_results(tmp_path: Path):
    """1組(スレッド×キーワード)の取得失敗で、他の収集結果まで失われてはならない。"""
    data_dir = tmp_path / "data"

    def fake_search(_story_id, keyword, _hits):
        if keyword == "失敗する語":
            raise requests.HTTPError("503 Server Error")
        return [FAKE_HIT]

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", side_effect=fake_search),
    ):
        hnjobs_search.run(
            _config(["成功する語", "失敗する語"]),
            data_dir=data_dir,
            db_path=tmp_path / "data" / "analysis.duckdb",
        )

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_unexpected_exception_does_not_discard_saved_results(tmp_path: Path):
    """想定外の例外がrunを貫通しても、それ以前の収集結果は保存済みでなければならない。"""
    data_dir = tmp_path / "data"

    def fake_search(_story_id, keyword, _hits):
        if keyword == "壊れる語":
            raise RuntimeError("想定外の例外")
        return [FAKE_HIT]

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", side_effect=fake_search),
        pytest.raises(RuntimeError),
    ):
        hnjobs_search.run(
            _config(["成功する語", "壊れる語"]),
            data_dir=data_dir,
            db_path=tmp_path / "data" / "analysis.duckdb",
        )

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1, "例外の前に収集した分がディスクに書かれていない"
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_malformed_entry_is_skipped_without_losing_others(tmp_path: Path):
    """必須フィールド(objectID)を欠く応答があっても、その1件だけを捨てて処理を続ける。"""
    data_dir = tmp_path / "data"
    broken = {k: v for k, v in FAKE_HIT.items() if k != "objectID"}
    other = {**FAKE_HIT, "objectID": "other456"}

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=_fake_list_threads),
        patch("sns_collector.hnjobs.search.search_thread", return_value=[broken, FAKE_HIT, other]),
    ):
        hnjobs_search.run(
            _config(["embedded"]), data_dir=data_dir, db_path=tmp_path / "data" / "analysis.duckdb"
        )

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 2


def test_thread_without_object_id_is_skipped(tmp_path: Path):
    """スレッド一覧の1件が壊れていても、残りのスレッドは収集する。"""
    data_dir = tmp_path / "data"
    searched: list[str] = []

    def fake_list(author, _hits):
        if author == "whoishiring":
            return [{"title": "Ask HN: Who is hiring? (July 2026)"}, HIRING_THREAD]
        return []

    def fake_search(story_id, _keyword, _hits):
        searched.append(story_id)
        return []

    with (
        patch("sns_collector.hnjobs.search.list_threads", side_effect=fake_list),
        patch("sns_collector.hnjobs.search.search_thread", side_effect=fake_search),
    ):
        hnjobs_search.run(
            _config(["embedded"], thread_kinds=["hiring"]),
            data_dir=data_dir,
            db_path=tmp_path / "data" / "analysis.duckdb",
        )

    assert searched == [HIRING_THREAD["objectID"]]


def test_no_matching_thread_does_not_create_output(tmp_path: Path):
    """対象スレッドが無いときに空のJSONLを作らない(後段の集計を汚さない)。"""
    data_dir = tmp_path / "data"

    with (
        patch("sns_collector.hnjobs.search.list_threads", return_value=[HIRED_THREAD]),
        patch("sns_collector.hnjobs.search.search_thread") as mock_search,
    ):
        hnjobs_search.run(
            _config(["embedded"]), data_dir=data_dir, db_path=tmp_path / "data" / "analysis.duckdb"
        )

    mock_search.assert_not_called()
    assert not list(data_dir.glob("*.jsonl"))
