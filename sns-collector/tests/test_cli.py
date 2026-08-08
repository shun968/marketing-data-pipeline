from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sns_collector import cli
from sns_collector.common.config import HackerNewsConfig

KEYWORDS_YAML = """
bluesky:
  keywords: ["語"]
youtube:
  keywords: ["語"]
hackernews:
  keywords: ["語"]
"""


@pytest.mark.parametrize("platform", ["bluesky", "youtube", "hackernews"])
def test_収集サブコマンドを全プラットフォームで登録している(platform: str):
    args = cli.parse_args([platform])
    assert args.command == platform


def test_extract_prepareのplatform引数はhackernewsを選べる(tmp_path: Path):
    args = cli.parse_args(["extract", "prepare", "--platform", "hackernews"])
    assert args.platform == ["hackernews"]


@pytest.mark.parametrize("platform", ["bluesky", "youtube", "hackernews"])
def test_収集コマンドは対応するrunと設定ロード関数へディスパッチする(tmp_path: Path, platform: str):
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text(KEYWORDS_YAML, encoding="utf-8")

    module, _load_fn = cli.COLLECTORS[platform]

    with patch.object(module, "run") as mock_run:
        code = cli.main(
            [platform, "--keywords", str(keywords_path), "--data-dir", str(tmp_path / "data")]
        )

    assert code == 0
    mock_run.assert_called_once()
    _config, kwargs = mock_run.call_args.args, mock_run.call_args.kwargs
    assert kwargs["data_dir"] == tmp_path / "data" / platform


def test_hackernewsのkeywords未設定は設定エラーになる(tmp_path: Path, capsys):
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text("hackernews: {}\n", encoding="utf-8")

    code = cli.main(
        ["hackernews", "--keywords", str(keywords_path), "--data-dir", str(tmp_path / "data")]
    )

    assert code == 1
    assert "hackernews.keywords" in capsys.readouterr().err


def test_load_hackernews_configは既定のtagsとhits_per_pageを持つ(tmp_path: Path):
    from sns_collector.common.config import load_hackernews_config

    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('hackernews:\n  keywords: ["語"]\n', encoding="utf-8")

    config = load_hackernews_config(keywords_path)
    assert isinstance(config, HackerNewsConfig)
    assert config.tags == "(story,comment)", "括弧が無いとAlgolia側でAND判定になり常に0件になる"
    assert config.hits_per_page == 50
