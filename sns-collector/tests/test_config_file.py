"""環境ファイル（APIキー）の読み取り位置の検証。

守りたいのは1点だけ。**カレントディレクトリから上へ .env を探しに行かないこと**。
探しに行く実装だと、ワークスペース内へ鍵を置く運用が成立してしまい、
devcontainer内のセッションの子プロセスから読める状態が戻る
（docs/isolation.md §3 経路3 / ADR-0012）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sns_collector.adapter.config_file import (
    ENV_FILE_VAR,
    load_github_config,
    load_youtube_config,
)
from sns_collector.domain.config import ConfigError

# 鍵と `SNS_COLLECTOR_ENV_FILE` の隔離は conftest.py の autouse fixture が行う。
# ここに置くと test_cli.py 側が環境依存で落ちる（同じ loader を触るため）


def _keywords_file(tmp_path: Path, section: str) -> Path:
    path = tmp_path / "keywords.yaml"
    path.write_text(f"{section}:\n  keywords:\n    - 検索語\n", encoding="utf-8")
    return path


def test_未設定ならカレント配下の環境ファイルを読まない(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("YOUTUBE_API_KEY=leaked\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError):
        load_youtube_config(_keywords_file(tmp_path, "youtube"))


def test_環境変数が指す場所から読む(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path / "outside" / ".env"
    outside.parent.mkdir()
    outside.write_text("YOUTUBE_API_KEY=abc\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VAR, str(outside))

    config = load_youtube_config(_keywords_file(tmp_path, "youtube"))

    assert config.api_key == "abc"


def test_指定先が無ければ探索へ落とさず失敗する(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """移設し損ねた鍵をワークスペース側から拾って動かない。

    黙って探索へ落ちると、移設できていないことに気づけないまま動き続ける。
    """
    (tmp_path / ".env").write_text("YOUTUBE_API_KEY=leaked\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "missing" / ".env"))

    with pytest.raises(ConfigError) as excinfo:
        load_youtube_config(_keywords_file(tmp_path, "youtube"))

    assert ENV_FILE_VAR in str(excinfo.value)


def test_鍵が任意の収集元は未設定でも動く(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GitHubトークンは任意（無くてもレート制限が下がるだけ）。

    ここを必須にすると、鍵の置き場を移す前の状態で収集が丸ごと止まる。
    """
    monkeypatch.chdir(tmp_path)

    config = load_github_config(_keywords_file(tmp_path, "github"))

    assert config.token is None
