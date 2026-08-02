"""パス解決の検証。

この画面はURLから受け取った文字列でファイルを開く箇所がある。
ここが緩むと、リポジトリ外の .env や鍵ファイルがブラウザから読める。
**「検知できること」と同じ重みで「正常なパスを弾かないこと」もテストする。**
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write

from dashboard.paths import OutsideRootError, relative_to_repo, repo_root, resolve_within


def test_リポジトリルートを環境変数で差し替えられる(repo: Path) -> None:
    assert repo_root() == repo.resolve()


def test_配下のパスを解決する(repo: Path) -> None:
    base = repo / "reports"
    write(base / "2026-08-01.md", "本文")
    assert resolve_within(base, "2026-08-01.md") == (base / "2026-08-01.md").resolve()


def test_サブディレクトリも解決する(repo: Path) -> None:
    base = repo / "reports"
    write(base / "weekly" / "w31.md", "本文")
    assert resolve_within(base, "weekly/w31.md").name == "w31.md"


@pytest.mark.parametrize(
    "attempt",
    [
        "../.env",
        "../../etc/passwd",
        "weekly/../../.env",
        "/etc/passwd",
    ],
)
def test_ルート外を指すパスを拒否する(repo: Path, attempt: str) -> None:
    base = repo / "reports"
    base.mkdir(parents=True)
    with pytest.raises(OutsideRootError):
        resolve_within(base, attempt)


def test_ドットの多い名前はルート内へ解決する(repo: Path) -> None:
    # `....//....//` は `..` の難読化ではなく、実在しないディレクトリ名。
    # 文字列で `..` を弾く実装だと誤って拒否するが、実パスで判定していれば
    # ルート内に落ちて「存在しないファイル」になる。
    # 呼び出し側はこれを404として扱う
    base = repo / "reports"
    base.mkdir(parents=True)
    resolved = resolve_within(base, "....//....//.env")
    assert base.resolve() in resolved.parents


def test_外を指すシンボリックリンクを拒否する(repo: Path) -> None:
    # `..` を文字列で弾くだけでは足りない。実パスで判定していることを固定する
    secret = write(repo / "secret.env", "KEY=1")
    base = repo / "reports"
    base.mkdir(parents=True)
    (base / "link.md").symlink_to(secret)

    with pytest.raises(OutsideRootError):
        resolve_within(base, "link.md")


def test_NUL文字を含むパスを拒否する(repo: Path) -> None:
    base = repo / "reports"
    base.mkdir(parents=True)
    with pytest.raises(OutsideRootError):
        resolve_within(base, "a\x00.md")


def test_リポジトリ相対の表示になる(repo: Path) -> None:
    path = write(repo / "docs" / "design.md", "本文")
    assert relative_to_repo(path) == "docs/design.md"


def test_リポジトリ外は絶対パスのまま返す(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("x", encoding="utf-8")
    assert relative_to_repo(outside).startswith("/")
