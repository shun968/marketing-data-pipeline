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
