from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


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


def _load_keywords_file(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_bluesky_config(path: Path) -> BlueskyConfig:
    raw = _load_keywords_file(path).get("bluesky", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に bluesky.keywords が定義されていません。")

    return BlueskyConfig(
        sort=raw.get("sort", "latest"),
        limit_per_keyword=int(raw.get("limit_per_keyword", 50)),
        keywords=list(keywords),
    )


def load_youtube_config(path: Path, env_path: Path | None = None) -> YouTubeConfig:
    load_dotenv(dotenv_path=env_path)
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        raise ConfigError(
            "必須の環境変数 YOUTUBE_API_KEY が未設定です。"
            " .env.example を参考に .env を作成してください。"
        )

    raw = _load_keywords_file(path).get("youtube", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に youtube.keywords が定義されていません。")

    return YouTubeConfig(
        api_key=api_key,
        order=raw.get("order", "relevance"),
        max_results_per_keyword=int(raw.get("max_results_per_keyword", 25)),
        region_code=raw.get("region_code", "JP"),
        relevance_language=raw.get("relevance_language", "ja"),
        keywords=list(keywords),
    )


def load_hackernews_config(path: Path) -> HackerNewsConfig:
    raw = _load_keywords_file(path).get("hackernews", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に hackernews.keywords が定義されていません。")

    return HackerNewsConfig(
        # Algoliaのtagsは括弧が無いとAND(=story かつ comment を同時に満たす、
        # 常に0件)になる。"(story,comment)"のようにOR対象を括弧で囲む必要がある
        tags=raw.get("tags", "(story,comment)"),
        hits_per_page=int(raw.get("hits_per_page", 50)),
        keywords=list(keywords),
    )


def load_github_config(path: Path, env_path: Path | None = None) -> GitHubConfig:
    load_dotenv(dotenv_path=env_path)
    # トークンは任意。無くても検索できる(レート制限が10 req/minへ下がるだけ)。
    # 必須にすると、キーワード候補を実データで検証する前段の作業まで
    # 資格情報の準備待ちになる(sns-collector/CLAUDE.md「質の確認に本収集を使わない」)
    token = os.environ.get("GITHUB_TOKEN", "") or None

    raw = _load_keywords_file(path).get("github", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に github.keywords が定義されていません。")

    return GitHubConfig(
        token=token,
        # is:issue を外すとPull Requestも混ざる
        qualifiers=raw.get("qualifiers", "is:issue"),
        per_page=int(raw.get("per_page", 50)),
        keywords=list(keywords),
    )


def load_reddit_config(path: Path, env_path: Path | None = None) -> RedditConfig:
    load_dotenv(dotenv_path=env_path)
    missing = [
        name
        for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
        if not os.environ.get(name, "")
    ]
    if missing:
        raise ConfigError(
            f"必須の環境変数 {', '.join(missing)} が未設定です。"
            " .env.example を参考に .env を作成してください。"
        )

    raw = _load_keywords_file(path).get("reddit", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に reddit.keywords が定義されていません。")

    return RedditConfig(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
        sort=raw.get("sort", "new"),
        time_filter=raw.get("time_filter", "month"),
        limit_per_keyword=int(raw.get("limit_per_keyword", 50)),
        keywords=list(keywords),
    )


def load_domain_ids(path: Path) -> list[str]:
    """config/domains.yaml の統制語彙。抽出結果の domain はこの範囲に限る。

    ここを読まずに列挙をコード側へ書くと、YAMLとコードの二重管理になる。
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    domains = raw.get("domains")
    if not isinstance(domains, list) or not domains:
        raise ConfigError(f"domains が空、または配列でない: {path}")

    ids = [d.get("id") for d in domains if isinstance(d, dict)]
    if not all(isinstance(i, str) and i for i in ids):
        raise ConfigError(f"id を持たないドメイン定義がある: {path}")
    return ids
