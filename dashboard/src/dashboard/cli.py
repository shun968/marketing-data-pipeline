"""モニタリング画面の起動。

**bind先を 127.0.0.1 に固定する。**
この画面は収集データ(投稿本文を含むレポート、収集ログ、キーワード実績)を
そのまま表示する。0.0.0.0 で待ち受けると、同一ネットワークの他端末から
収集データが読める状態になる。ホストを引数で受け取らないのは、
「うっかり外へ開く」経路を作らないため。

外部から見る必要が出た場合は、この既定を変えるのではなく
SSHのポートフォワードを使う。
"""

from __future__ import annotations

import argparse

import uvicorn

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dashboard",
        description="開発ルール・ADR・レポート・ガードレールメトリクスのモニタリング画面",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"待ち受けポート（既定: {DEFAULT_PORT}）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="ソース変更時に自動再起動する（開発用）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    print(f"モニタリング画面: http://{BIND_HOST}:{args.port}")
    uvicorn.run(
        "dashboard.app:create_app",
        factory=True,
        host=BIND_HOST,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
