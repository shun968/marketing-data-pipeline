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


def test_extract_prepareのprompts_dir引数はPathとして解析される():
    args = cli.parse_args(["extract", "prepare", "--prompts-dir", "/tmp/custom-prompts"])
    assert args.prompts_dir == Path("/tmp/custom-prompts")


def test_extract_prepareのprompts_dir未指定はNone():
    args = cli.parse_args(["extract", "prepare"])
    assert args.prompts_dir is None


def test_extract_prepareはprompts_dirをprepareへ渡す(tmp_path: Path):
    domains_path = tmp_path / "domains.yaml"
    domains_path.write_text("domains:\n  - id: other\n", encoding="utf-8")
    prompts_dir = tmp_path / "custom_prompts"

    with patch.object(cli.extract_mod, "prepare") as mock_prepare:
        mock_prepare.return_value = None
        code = cli.main(
            [
                "extract",
                "prepare",
                "--data-dir",
                str(tmp_path / "data"),
                "--domains",
                str(domains_path),
                "--prompts-dir",
                str(prompts_dir),
            ]
        )

    assert code == 0
    assert mock_prepare.call_args.kwargs["prompts_dir"] == prompts_dir


@pytest.mark.parametrize("platform", ["bluesky", "youtube", "hackernews"])
def test_収集コマンドは対応するrunと設定ロード関数へディスパッチする(
    tmp_path: Path, platform: str, monkeypatch: pytest.MonkeyPatch
):
    # youtubeの設定ロードは環境変数必須。CIには無いためテスト内で明示的に与える
    monkeypatch.setenv("YOUTUBE_API_KEY", "dummy")
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
