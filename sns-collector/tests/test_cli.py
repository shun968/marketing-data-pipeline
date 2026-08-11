from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from sns_collector.domain.collect import CollectSummary
from sns_collector.domain.config import HackerNewsConfig
from sns_collector.entrypoint import cli

KEYWORDS_YAML = """
bluesky:
  keywords: ["語"]
youtube:
  keywords: ["語"]
hackernews:
  keywords: ["語"]
hnjobs:
  keywords: ["語"]
github:
  keywords: ["語"]
reddit:
  keywords: ["語"]
"""


@pytest.mark.parametrize("platform", list(cli.COLLECTORS))
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

    with patch.object(cli.extract_prepare, "prepare") as mock_prepare:
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


@pytest.mark.parametrize("platform", list(cli.COLLECTORS))
def test_収集コマンドは設定を読んでcollectユースケースへ結線する(
    tmp_path: Path, platform: str, monkeypatch: pytest.MonkeyPatch, capsys
):
    """entrypoint の仕事は、設定を読んで I/O を結線することだけである（ADR-0011）。

    収集の手順そのものは usecase 側にあり、ここでは呼び分けと結線だけを見る。
    """
    # youtube/redditの設定ロードは環境変数必須。CIには無いためテスト内で明示的に与える。
    # GITHUB_TOKENは任意のため与えない(未設定でも通ることの回帰にもなる)
    monkeypatch.setenv("YOUTUBE_API_KEY", "dummy")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "dummy")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "dummy")
    monkeypatch.setenv("REDDIT_USER_AGENT", "test:app:1.0 (by /u/test)")
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text(KEYWORDS_YAML, encoding="utf-8")

    seen: dict = {}

    def fake_tasks(config, collected_at, notify):
        # 実際の tasks() は通信する(reddit のトークン取得・hnjobs のスレッド一覧)
        seen["config"] = config
        return []

    monkeypatch.setitem(
        cli.COLLECTORS, platform, replace(cli.COLLECTORS[platform], build_tasks=fake_tasks)
    )

    with patch.object(cli, "collect", return_value=CollectSummary()) as mock_collect:
        code = cli.main(
            [platform, "--keywords", str(keywords_path), "--data-dir", str(tmp_path / "data")]
        )

    assert code == 0
    assert seen["config"].keywords == ["語"], (
        "keywords.yaml のこのプラットフォームの節を読んでいない"
    )
    mock_collect.assert_called_once()

    # JSONLの出力先はプラットフォームごとに分かれる
    assert str(tmp_path / "data" / platform) in capsys.readouterr().out


def test_収集レジストリとアダプタレジストリのキーが一致する():
    """収集モジュールを足してアダプタを忘れると、JSONLは書けるがDB投入でKeyErrorになる。

    JSONLは残るのでデータは失われないが、その run 以降が落ちる。型チェッカーが無い
    この構成では、レジストリの整合をこのテストで実行可能な形にして担保する。
    """
    from sns_collector.adapter.db.mapping import ADAPTERS

    assert set(cli.COLLECTORS) == set(ADAPTERS)


@pytest.mark.parametrize("platform", list(cli.COLLECTORS))
def test_収集レジストリは結線に必要な3つを揃えて持つ(platform: str):
    spec = cli.COLLECTORS[platform]
    assert callable(spec.load_config)
    assert callable(spec.build_tasks)
    assert spec.unit, "ログの語が空だとメッセージが崩れる"


def test_hackernewsのkeywords未設定は設定エラーになる(tmp_path: Path, capsys):
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text("hackernews: {}\n", encoding="utf-8")

    code = cli.main(
        ["hackernews", "--keywords", str(keywords_path), "--data-dir", str(tmp_path / "data")]
    )

    assert code == 1
    assert "hackernews.keywords" in capsys.readouterr().err


def test_load_hackernews_configは既定のtagsとhits_per_pageを持つ(tmp_path: Path):
    from sns_collector.adapter.config_file import load_hackernews_config

    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('hackernews:\n  keywords: ["語"]\n', encoding="utf-8")

    config = load_hackernews_config(keywords_path)
    assert isinstance(config, HackerNewsConfig)
    assert config.tags == "(story,comment)", "括弧が無いとAlgolia側でAND判定になり常に0件になる"
    assert config.hits_per_page == 50


def test_load_github_configはトークン未設定でもNoneで通る(tmp_path: Path, monkeypatch):
    from sns_collector.adapter.config_file import load_github_config

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('github:\n  keywords: ["語"]\n', encoding="utf-8")

    config = load_github_config(keywords_path)
    assert config.token is None
    assert config.qualifiers == "is:issue", "外すとPull Requestも混ざる"
    assert config.per_page == 50


def test_load_github_configはトークンを環境変数から読む(tmp_path: Path, monkeypatch):
    from sns_collector.adapter.config_file import load_github_config

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('github:\n  keywords: ["語"]\n', encoding="utf-8")

    config = load_github_config(keywords_path)
    assert config.token == "ghp_dummy"


def test_githubのkeywords未設定は設定エラーになる(tmp_path: Path):
    from sns_collector.adapter.config_file import load_github_config
    from sns_collector.domain.config import ConfigError

    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text("github: {}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="github.keywords"):
        load_github_config(keywords_path)


def test_reddit_の環境変数が欠けていたら不足分をまとめて報告する(tmp_path: Path, monkeypatch):
    from sns_collector.adapter.config_file import load_reddit_config
    from sns_collector.domain.config import ConfigError

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('reddit:\n  keywords: ["語"]\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_reddit_config(keywords_path)

    message = str(exc_info.value)
    assert "REDDIT_CLIENT_ID" in message
    assert "REDDIT_CLIENT_SECRET" in message
    assert "REDDIT_USER_AGENT" in message


def test_load_reddit_configは既定のsortとtime_filterを持つ(tmp_path: Path, monkeypatch):
    from sns_collector.adapter.config_file import load_reddit_config
    from sns_collector.domain.config import RedditConfig

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "test:app:1.0 (by /u/test)")
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('reddit:\n  keywords: ["語"]\n', encoding="utf-8")

    config = load_reddit_config(keywords_path)
    assert isinstance(config, RedditConfig)
    assert config.sort == "new"
    assert config.time_filter == "month"
    assert config.limit_per_keyword == 50


def test_redditのkeywords未設定は設定エラーになる(tmp_path: Path, monkeypatch):
    from sns_collector.adapter.config_file import load_reddit_config
    from sns_collector.domain.config import ConfigError

    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "test:app:1.0 (by /u/test)")
    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text("reddit: {}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="reddit.keywords"):
        load_reddit_config(keywords_path)


def test_値を書かない設定キーは既定値へ倒す(tmp_path: Path):
    """`thread_kinds:` のように値を省くと None が入る。

    `raw.get(key, default)` はキーが存在して None のとき既定値を使わないため、
    `list(None)` / `int(None)` が TypeError になる。cli.main は ConfigError しか
    案内しないので、利用者には素のトレースバックだけが見える。
    """
    from sns_collector.adapter.config_file import load_bluesky_config, load_hnjobs_config

    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text(
        'bluesky:\n  sort:\n  limit_per_keyword:\n  keywords: ["語"]\n'
        'hnjobs:\n  thread_kinds:\n  thread_limit:\n  keywords: ["語"]\n',
        encoding="utf-8",
    )

    bluesky = load_bluesky_config(keywords_path)
    assert bluesky.sort == "latest"
    assert bluesky.limit_per_keyword == 50

    hnjobs = load_hnjobs_config(keywords_path)
    assert hnjobs.thread_kinds == ["hiring", "freelancer"]
    assert hnjobs.thread_limit == 3, "コードの既定値は config/keywords.yaml と揃える"


def test_0以下の件数指定は設定エラーになる(tmp_path: Path):
    """0は「静かに何も集めない」設定になり、収集できていないことに気づけない。"""
    from sns_collector.adapter.config_file import load_hnjobs_config
    from sns_collector.domain.config import ConfigError

    keywords_path = tmp_path / "keywords.yaml"
    keywords_path.write_text('hnjobs:\n  thread_limit: 0\n  keywords: ["語"]\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="thread_limit"):
        load_hnjobs_config(keywords_path)
