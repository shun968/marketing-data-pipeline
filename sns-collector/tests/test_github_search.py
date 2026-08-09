from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from sns_collector.common.config import GitHubConfig
from sns_collector.github import search as github_search


def _config(keywords: list[str]) -> GitHubConfig:
    return GitHubConfig(token=None, qualifiers="is:issue", per_page=50, keywords=keywords)


FAKE_ISSUE = {
    "id": 2345678901,
    "number": 42,
    "title": "衝突回避のログが読みにくい",
    "body": "本文だよ",
    "state": "open",
    "user": {"login": "someone", "id": 9999},
    "comments": 3,
    "reactions": {"total_count": 1},
    "labels": [{"name": "bug"}],
    "repository_url": "https://api.github.com/repos/owner/repo",
    "created_at": "2026-08-08T00:33:37Z",
    "updated_at": "2026-08-08T01:00:00Z",
    "html_url": "https://github.com/owner/repo/issues/42",
}


def test_run_writes_new_items_and_skips_duplicates(tmp_path: Path):
    config = _config(["collision avoidance"])
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    with patch("sns_collector.github.search.search_issues", return_value=[FAKE_ISSUE]):
        github_search.run(config, data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    lines = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["issue_id"] == "2345678901"
    assert record["repo_full_name"] == "owner/repo"

    with patch("sns_collector.github.search.search_issues", return_value=[FAKE_ISSUE]):
        github_search.run(config, data_dir=data_dir, db_path=db_path)

    lines_after = output_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines_after) == 1


def test_failed_keyword_does_not_discard_other_results(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword, *_args):
        if keyword == "失敗する語":
            raise requests.HTTPError("503 Server Error")
        return [FAKE_ISSUE]

    with patch("sns_collector.github.search.search_issues", side_effect=fake_search):
        github_search.run(_config(["成功する語", "失敗する語"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1
    assert db_path.exists(), "分析DBが作られていない"


def test_unexpected_exception_does_not_discard_saved_results(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    def fake_search(keyword, *_args):
        if keyword == "壊れる語":
            raise RuntimeError("想定外の例外")
        return [FAKE_ISSUE]

    with (
        patch("sns_collector.github.search.search_issues", side_effect=fake_search),
        pytest.raises(RuntimeError),
    ):
        github_search.run(_config(["成功する語", "壊れる語"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1, "例外の前に収集した分がディスクに書かれていない"
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 1


def test_malformed_item_is_skipped_without_losing_others(tmp_path: Path):
    data_dir = tmp_path / "data"
    db_path = tmp_path / "data" / "analysis.duckdb"

    broken_issue = {k: v for k, v in FAKE_ISSUE.items() if k != "id"}
    other_issue = {**FAKE_ISSUE, "id": 999}

    with patch(
        "sns_collector.github.search.search_issues",
        return_value=[broken_issue, FAKE_ISSUE, other_issue],
    ):
        github_search.run(_config(["キーワード"]), data_dir=data_dir, db_path=db_path)

    output_files = list(data_dir.glob("*.jsonl"))
    assert len(output_files) == 1
    assert len(output_files[0].read_text(encoding="utf-8").splitlines()) == 2
