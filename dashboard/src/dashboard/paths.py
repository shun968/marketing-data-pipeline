"""リポジトリ内のパス解決と、読み取りを許可する範囲の定義。

この画面は収集データ(sns-collector/reports, state/.logs)を読む。
パスをURLから受け取る箇所があるため、**解決後のパスが許可ルート配下に
あることを必ず検証する**。ここを緩めるとディレクトリトラバーサルで
リポジトリ外のファイル(.env、~/.ssh など)が読める。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class OutsideRootError(Exception):
    """許可ルートの外を指すパスが渡された。"""


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """リポジトリのルート。

    環境変数 DASHBOARD_REPO_ROOT で差し替えられる。テストは使い捨ての
    ディレクトリを指すため、これが無いと実リポジトリを読んでしまう。
    """
    override = os.environ.get("DASHBOARD_REPO_ROOT")
    if override:
        return Path(override).resolve()

    # このファイルは <root>/dashboard/src/dashboard/paths.py にある
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Roots:
    """読み取りを許可するディレクトリ。

    ここに無いディレクトリは画面から一切読まない。
    """

    repo: Path
    docs: Path
    adr: Path
    skills: Path
    reports: Path
    collector_logs: Path
    metrics: Path


def roots() -> Roots:
    root = repo_root()
    return Roots(
        repo=root,
        docs=root / "docs",
        adr=root / "docs" / "adr",
        skills=root / ".claude" / "skills",
        reports=root / "sns-collector" / "reports",
        collector_logs=root / "sns-collector" / "state" / ".logs",
        metrics=root / ".metrics",
    )


def resolve_within(base: Path, relative: str) -> Path:
    """base 配下のパスへ解決する。外を指していたら例外にする。

    `..` を含む文字列を弾くだけでは足りない。シンボリックリンクが
    外を指す場合があるため、**解決後の実パスで判定する**。
    """
    if "\x00" in relative:
        raise OutsideRootError(relative)

    base_resolved = base.resolve()
    candidate = (base_resolved / relative).resolve()

    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise OutsideRootError(relative)
    return candidate


def relative_to_repo(path: Path) -> str:
    """表示用。リポジトリ外なら絶対パスをそのまま返す。"""
    try:
        return str(path.resolve().relative_to(repo_root()))
    except ValueError:
        return str(path)
