from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bluesky import search as bluesky_search
from .common.config import ConfigError, load_bluesky_config, load_youtube_config
from .youtube import search as youtube_search

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KEYWORDS_PATH = PROJECT_ROOT / "config" / "keywords.yaml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_STATE_DIR = PROJECT_ROOT / "state"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SNS(Bluesky/YouTube)をキーワード検索し、投稿・動画データをJSONLに保存する"
    )
    parser.add_argument("platform", choices=["bluesky", "youtube"], help="収集対象プラットフォーム")
    parser.add_argument(
        "--keywords", type=Path, default=DEFAULT_KEYWORDS_PATH, help="keywords.yamlのパス"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="JSONL出力先ルート")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help="SeenStore格納先")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.platform == "bluesky":
            config = load_bluesky_config(args.keywords)
            bluesky_search.run(
                config,
                data_dir=args.data_dir / "bluesky",
                state_path=args.state_dir / "bluesky_seen.json",
            )
        else:
            config = load_youtube_config(args.keywords)
            youtube_search.run(
                config,
                data_dir=args.data_dir / "youtube",
                state_path=args.state_dir / "youtube_seen.json",
            )
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
