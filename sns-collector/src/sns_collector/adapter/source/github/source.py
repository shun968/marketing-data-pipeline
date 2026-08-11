from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....domain.collect import CollectTask, Record
from ....domain.config import GitHubConfig
from ...http import source_errors
from .client import search_issues
from .dto import GitHubIssue


def tasks(
    config: GitHubConfig, collected_at: datetime, notify: Callable[[str], None]
) -> list[CollectTask]:
    return [_task(config, keyword, collected_at) for keyword in config.keywords]


def _task(config: GitHubConfig, keyword: str, collected_at: datetime) -> CollectTask:
    def fetch() -> list[dict]:
        with source_errors():
            return search_issues(keyword, config.qualifiers, config.per_page, config.token)

    def parse(raw: dict) -> Record:
        issue = GitHubIssue.from_issue(raw, keyword, collected_at)
        return Record(native_id=issue.issue_id, payload=issue.to_dict())

    return CollectTask(label=f"github:{keyword}", keyword=keyword, fetch=fetch, parse=parse)
