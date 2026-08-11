from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sns_collector.adapter.source.github.dto import GitHubIssue

COLLECTED_AT = datetime(2026, 8, 8, tzinfo=UTC)

FAKE_ISSUE = {
    "id": 2345678901,
    "number": 42,
    "title": "衝突回避のログが読みにくい",
    "body": "本文だよ",
    "state": "open",
    "user": {"login": "someone", "id": 9999},
    "comments": 3,
    "reactions": {"total_count": 1},
    "labels": [{"name": "bug"}, {"name": "help wanted"}],
    "repository_url": "https://api.github.com/repos/owner/repo",
    "created_at": "2026-08-08T00:33:37Z",
    "updated_at": "2026-08-08T01:00:00Z",
    "html_url": "https://github.com/owner/repo/issues/42",
}


def test_issueのidと本文とURLを取り込む():
    item = GitHubIssue.from_issue(FAKE_ISSUE, "kw", COLLECTED_AT)

    assert item.issue_id == "2345678901"
    assert item.text == "衝突回避のログが読みにくい\n本文だよ"
    assert item.url == "https://github.com/owner/repo/issues/42"


def test_repository_urlからowner_nameを切り出す():
    item = GitHubIssue.from_issue(FAKE_ISSUE, "kw", COLLECTED_AT)
    assert item.repo_full_name == "owner/repo"


def test_bodyが空のissueは本文がタイトルだけになる():
    item = GitHubIssue.from_issue({**FAKE_ISSUE, "body": None}, "kw", COLLECTED_AT)
    assert item.text == "衝突回避のログが読みにくい"
    assert item.body is None


def test_labelsは名前の配列になる():
    item = GitHubIssue.from_issue(FAKE_ISSUE, "kw", COLLECTED_AT)
    assert item.labels == ["bug", "help wanted"]


def test_userがNoneでも読める():
    """削除済みアカウントではuserがNoneになりうる。"""
    item = GitHubIssue.from_issue({**FAKE_ISSUE, "user": None}, "kw", COLLECTED_AT)
    assert item.author == ""
    assert item.author_id == ""


def test_repository_urlが無ければ空文字にする():
    item = GitHubIssue.from_issue({**FAKE_ISSUE, "repository_url": None}, "kw", COLLECTED_AT)
    assert item.repo_full_name == ""


def test_必須フィールドが無ければ例外():
    with pytest.raises(KeyError):
        GitHubIssue.from_issue({"number": 1}, "kw", COLLECTED_AT)
