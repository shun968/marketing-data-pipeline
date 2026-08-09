from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


def _repo_full_name(repository_url: Any) -> str:
    """`https://api.github.com/repos/<owner>/<name>` から `<owner>/<name>` を切り出す。

    検索APIのレスポンスにはrepositoryオブジェクトが含まれないため、これが唯一の経路。
    切り出せなくても行を捨てる理由にはしない。
    """
    if not isinstance(repository_url, str) or not repository_url:
        return ""
    parts = repository_url.rstrip("/").split("/")
    if len(parts) < 2:
        return ""
    return "/".join(parts[-2:])


def _label_names(labels: Any) -> list[str]:
    if not isinstance(labels, list):
        return []
    names = []
    for label in labels:
        if isinstance(label, dict):
            names.append(str(label.get("name", "")))
        elif isinstance(label, str):
            names.append(label)
    return names


@dataclass(frozen=True)
class GitHubIssue:
    issue_id: str
    keyword: str
    text: str
    title: str
    body: str | None
    repo_full_name: str
    number: int
    state: str
    author: str
    author_id: str
    comments: int
    reactions: int
    labels: list[str]
    created_at: str
    updated_at: str
    url: str
    collected_at: str
    raw: dict[str, Any]

    @classmethod
    def from_issue(cls, issue: dict[str, Any], keyword: str, collected_at: datetime) -> GitHubIssue:
        issue_id = str(issue["id"])
        title = issue.get("title") or ""
        body = issue.get("body") or None
        text = "\n".join(part for part in (title, body) if part)
        user = issue.get("user") or {}
        reactions = issue.get("reactions") or {}

        return cls(
            issue_id=issue_id,
            keyword=keyword,
            text=text,
            title=title,
            body=body,
            repo_full_name=_repo_full_name(issue.get("repository_url")),
            number=issue.get("number") or 0,
            state=issue.get("state") or "",
            author=user.get("login", ""),
            author_id=str(user.get("id", "")),
            comments=issue.get("comments") or 0,
            reactions=reactions.get("total_count") or 0,
            labels=_label_names(issue.get("labels")),
            created_at=issue.get("created_at", ""),
            updated_at=issue.get("updated_at", ""),
            url=issue.get("html_url", ""),
            collected_at=collected_at.isoformat(),
            raw=issue,
        )

    def to_dict(self) -> dict:
        return asdict(self)
