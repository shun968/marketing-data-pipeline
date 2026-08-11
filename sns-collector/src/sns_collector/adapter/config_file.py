"""設定ファイル（config/keywords.yaml）と環境変数（.env）の読み取り。

設定の形は `domain/config.py` にある。ここは「どこから読むか」だけを持つ。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ..domain.config import (
    BlueskyConfig,
    ConfigError,
    Domain,
    GitHubConfig,
    HackerNewsConfig,
    HackerNewsJobsConfig,
    RedditConfig,
    YouTubeConfig,
)


def _load_keywords_file(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _str_option(raw: dict, key: str, default: str) -> str:
    """設定の文字列値。**キーが在って値が空の場合を既定値へ倒す。**

    `raw.get(key, default)` はキーが存在して None のとき既定値を使わない。
    YAMLで `sort:` と書いて値を省くと None が入り、そのままAPIへ渡って
    意味の分からない失敗になる。`hnjobs/client.py` で
    `payload.get("hits") or []` として塞いだのと同じ穴が、設定側にもある。
    """
    value = raw.get(key)
    return str(value) if value else default


def _int_option(raw: dict, key: str, default: int, *, minimum: int = 1) -> int:
    """設定の整数値。空なら既定値、下限を割ったら ConfigError。

    `int(None)` の TypeError は `cli.main` が捕まえないため、利用者には
    素のトレースバックだけが見える。0以下は「静かに何も集めない」設定になり、
    収集できていないことに気づけない。
    """
    value = raw.get(key)
    if value is None:
        return default
    number = int(value)
    if number < minimum:
        raise ConfigError(f"{key} は {minimum} 以上である必要があります（指定値: {number}）。")
    return number


def _list_option(raw: dict, key: str, default: list[str]) -> list[str]:
    value = raw.get(key)
    return list(value) if value else list(default)


def load_bluesky_config(path: Path) -> BlueskyConfig:
    raw = _load_keywords_file(path).get("bluesky", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に bluesky.keywords が定義されていません。")

    return BlueskyConfig(
        sort=_str_option(raw, "sort", "latest"),
        limit_per_keyword=_int_option(raw, "limit_per_keyword", 50),
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
        order=_str_option(raw, "order", "relevance"),
        max_results_per_keyword=_int_option(raw, "max_results_per_keyword", 25),
        region_code=_str_option(raw, "region_code", "JP"),
        relevance_language=_str_option(raw, "relevance_language", "ja"),
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
        tags=_str_option(raw, "tags", "(story,comment)"),
        hits_per_page=_int_option(raw, "hits_per_page", 50),
        keywords=list(keywords),
    )


def load_hnjobs_config(path: Path) -> HackerNewsJobsConfig:
    raw = _load_keywords_file(path).get("hnjobs", {})
    keywords = raw.get("keywords", [])
    if not keywords:
        raise ConfigError(f"{path} に hnjobs.keywords が定義されていません。")

    return HackerNewsJobsConfig(
        # 既定は求人と案件のみ。求職スレッド(hired)は「金を出す側」ではないため採らない。
        # 値の妥当性は adapter/source/hnjobs/source.py がタスク生成時に検査する
        thread_kinds=_list_option(raw, "thread_kinds", ["hiring", "freelancer"]),
        thread_limit=_int_option(raw, "thread_limit", 3),
        hits_per_page=_int_option(raw, "hits_per_page", 50),
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
        qualifiers=_str_option(raw, "qualifiers", "is:issue"),
        per_page=_int_option(raw, "per_page", 50),
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
        sort=_str_option(raw, "sort", "new"),
        time_filter=_str_option(raw, "time_filter", "month"),
        limit_per_keyword=_int_option(raw, "limit_per_keyword", 50),
        keywords=list(keywords),
    )


def load_domains(path: Path) -> list[Domain]:
    """config/domains.yaml の統制語彙。抽出結果の domain はこの範囲に限る。

    ここを読まずに列挙をコード側へ書くと、YAMLとコードの二重管理になる。
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("domains")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"domains が空、または配列でない: {path}")

    domains = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        domain_id = entry.get("id")
        if not isinstance(domain_id, str) or not domain_id:
            raise ConfigError(f"id を持たないドメイン定義がある: {path}")
        domains.append(
            Domain(
                id=domain_id,
                label=str(entry.get("label") or domain_id),
                boundary=str(entry["boundary"]) if entry.get("boundary") else None,
            )
        )
    return domains


def load_domain_ids(path: Path) -> list[str]:
    return [domain.id for domain in load_domains(path)]
