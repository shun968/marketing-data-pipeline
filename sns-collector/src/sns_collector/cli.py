from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .bluesky import search as bluesky_search
from .common.config import ConfigError, load_bluesky_config, load_youtube_config
from .db import connect, current_version, database_path, latest_version, load_all
from .youtube import search as youtube_search

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KEYWORDS_PATH = PROJECT_ROOT / "config" / "keywords.yaml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"YYYY-MM-DD 形式で指定する: {value}") from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SNS(Bluesky/YouTube)を検索して収集し、DuckDBの分析ストアへ取り込む"
    )
    # cron が `sns-collector bluesky` を直接呼ぶ。この呼び出し形を壊さないこと
    sub = parser.add_subparsers(dest="command", required=True)

    for platform in ("bluesky", "youtube"):
        collect = sub.add_parser(platform, help=f"{platform}を検索して収集する")
        collect.add_argument(
            "--keywords", type=Path, default=DEFAULT_KEYWORDS_PATH, help="keywords.yamlのパス"
        )
        collect.add_argument(
            "--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="JSONL出力先ルート"
        )
        collect.add_argument("--db", type=Path, default=None, help="分析DBのパス")

    db = sub.add_parser("db", help="分析ストアの操作")
    db_sub = db.add_subparsers(dest="db_command", required=True)

    db_init = db_sub.add_parser("init", help="スキーマを作成・更新する")
    db_init.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    db_init.add_argument("--db", type=Path, default=None)

    db_load = db_sub.add_parser("load", help="収集済みJSONLをDBへ取り込む(冪等)")
    db_load.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    db_load.add_argument("--db", type=Path, default=None)
    db_load.add_argument(
        "--since", type=_iso_date, default=None, help="この収集日以降のJSONLだけを対象にする"
    )

    return parser.parse_args(argv)


def _db_path(args: argparse.Namespace) -> Path:
    return args.db or database_path(args.data_dir)


def _run_db(args: argparse.Namespace) -> int:
    db_path = _db_path(args)

    if args.db_command == "init":
        with connect(db_path) as conn:
            print(f"スキーマ: v{current_version(conn)} / 最新: v{latest_version()}")
            print(f"分析DB: {db_path}")
        return 0

    with connect(db_path) as conn:
        results = load_all(conn, args.data_dir, since=args.since)
        for platform, result in results.items():
            print(
                f"[{platform}] ファイル: {result.files}件 "
                f"/ 新規: {result.inserted}件 / 既知: {result.updated}件 "
                f"/ スキップ: {result.skipped}件"
            )
        total = conn.execute("SELECT count(*) FROM posts").fetchone()[0]
        print(f"posts 合計: {total}件 ({db_path})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.command == "db":
            return _run_db(args)

        if args.command == "bluesky":
            bluesky_search.run(
                load_bluesky_config(args.keywords),
                data_dir=args.data_dir / "bluesky",
                db_path=_db_path(args),
            )
        else:
            youtube_search.run(
                load_youtube_config(args.keywords),
                data_dir=args.data_dir / "youtube",
                db_path=_db_path(args),
            )
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
