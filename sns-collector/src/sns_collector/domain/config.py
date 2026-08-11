"""収集の設定の形。

どこから読むか（YAML / 環境変数）は adapter が知る。ここは形だけを持つ。
"""

from __future__ import annotations

from dataclasses import dataclass


class ConfigError(Exception):
    """設定が足りない・値が不正。利用者が直せるため、呼び出し側は要点だけを見せる。"""


@dataclass(frozen=True)
class Domain:
    """観測対象ドメイン。`insights.domain` の統制語彙（config/domains.yaml）。

    `boundary` は隣接ドメインとの境界で、抽出プロンプトへ渡る。
    domains.yaml の `note`（散文）は渡らないため、**分類に効かせたい区別は
    boundary に書く**。ここが空だと、抽出側はid文字列しか知らないまま
    `edge_ai` と `embedded_dev` を選ぶことになる。
    """

    id: str
    label: str
    boundary: str | None = None


@dataclass(frozen=True)
class BlueskyConfig:
    sort: str
    limit_per_keyword: int
    keywords: list[str]


@dataclass(frozen=True)
class YouTubeConfig:
    api_key: str
    order: str
    max_results_per_keyword: int
    region_code: str
    relevance_language: str
    keywords: list[str]


@dataclass(frozen=True)
class HackerNewsConfig:
    tags: str
    hits_per_page: int
    keywords: list[str]


@dataclass(frozen=True)
class HackerNewsJobsConfig:
    thread_kinds: list[str]
    thread_limit: int
    hits_per_page: int
    keywords: list[str]


@dataclass(frozen=True)
class GitHubConfig:
    token: str | None
    qualifiers: str
    per_page: int
    keywords: list[str]


@dataclass(frozen=True)
class RedditConfig:
    client_id: str
    client_secret: str
    user_agent: str
    sort: str
    time_filter: str
    limit_per_keyword: int
    keywords: list[str]
