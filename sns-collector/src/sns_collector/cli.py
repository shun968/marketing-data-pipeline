from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import duckdb

from . import embed as embed_mod
from . import extract as extract_mod
from . import graph as graph_mod
from . import report as report_mod
from . import search as search_mod
from .bluesky import search as bluesky_search
from .common.config import (
    ConfigError,
    load_bluesky_config,
    load_domain_ids,
    load_github_config,
    load_hackernews_config,
    load_reddit_config,
    load_youtube_config,
)
from .db import connect, current_version, database_path, latest_version, load_all
from .extract.prepare import DEFAULT_PLATFORMS
from .github import search as github_search
from .hackernews import search as hackernews_search
from .keyword_quality import compute_keyword_stats
from .reddit import search as reddit_search
from .youtube import search as youtube_search

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KEYWORDS_PATH = PROJECT_ROOT / "config" / "keywords.yaml"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DOMAINS_PATH = PROJECT_ROOT / "config" / "domains.yaml"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"

# 収集コマンド名 -> (収集モジュール, 設定ロード関数)。
# サブパーサの登録・実行時ディスパッチの両方をこの1箇所から辿れるようにする。
#
# **モジュールを持つ。関数を直接束ねない。** `bluesky_search.run` を import時に
# 直接評価して辞書へ入れると、テストが `patch("...bluesky.search.run")` で
# 差し替えても、辞書には差し替え前の関数オブジェクトが残ったままになる。
# モジュールを持てば `.run` の参照は呼び出し時に解決され、既存のパッチ手法と噛み合う。
COLLECTORS = {
    "bluesky": (bluesky_search, load_bluesky_config),
    "youtube": (youtube_search, load_youtube_config),
    "hackernews": (hackernews_search, load_hackernews_config),
    "github": (github_search, load_github_config),
    "reddit": (reddit_search, load_reddit_config),
}


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"YYYY-MM-DD 形式で指定する: {value}") from e


def _bool_arg(value: str) -> bool:
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"true/false で指定する: {value}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "SNS(Bluesky/YouTube/Hacker News/GitHub/Reddit)を検索して収集し、"
            "DuckDBの分析ストアへ取り込む"
        )
    )
    # cron が `sns-collector bluesky` を直接呼ぶ。この呼び出し形を壊さないこと
    sub = parser.add_subparsers(dest="command", required=True)

    for platform in COLLECTORS:
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

    ex = sub.add_parser("extract", help="構造化抽出のバッチ操作")
    ex_sub = ex.add_subparsers(dest="extract_command", required=True)

    ex_prepare = ex_sub.add_parser("prepare", help="未抽出の投稿をバッチへ書き出す")
    ex_prepare.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ex_prepare.add_argument("--db", type=Path, default=None)
    ex_prepare.add_argument("--domains", type=Path, default=DEFAULT_DOMAINS_PATH)
    ex_prepare.add_argument("--limit", type=int, default=20, help="1バッチの件数")
    ex_prepare.add_argument("--version", default="v2", help="抽出プロンプトのバージョン")
    ex_prepare.add_argument(
        "--reextract",
        metavar="VERSION",
        help="この版で抽出済みの投稿を pending へ戻してから選ぶ",
    )
    ex_prepare.add_argument(
        "--platform",
        action="append",
        choices=list(COLLECTORS),
        help="抽出対象のプラットフォーム(既定: bluesky)。複数指定可",
    )
    ex_prepare.add_argument(
        "--prompts-dir",
        type=Path,
        default=None,
        help="抽出プロンプトの探索先(既定: sns-collector/prompts)",
    )

    ex_load = ex_sub.add_parser("load", help="抽出結果を検証してDBへ入れる")
    ex_load.add_argument("batch_id")
    ex_load.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ex_load.add_argument("--db", type=Path, default=None)
    ex_load.add_argument("--domains", type=Path, default=DEFAULT_DOMAINS_PATH)

    ex_status = ex_sub.add_parser("status", help="抽出待ち件数と未取り込みバッチ")
    ex_status.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ex_status.add_argument("--db", type=Path, default=None)

    kw = sub.add_parser("keywords", help="キーワードの改訂支援")
    kw_sub = kw.add_subparsers(dest="keywords_command", required=True)

    kw_quality = kw_sub.add_parser(
        "quality", help="キーワード別に、困りごと表現の代理指標を集計する"
    )
    kw_quality.add_argument("--platform", required=True, choices=list(COLLECTORS))
    kw_quality.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    kw_quality.add_argument("--db", type=Path, default=None)

    em = sub.add_parser("embed", help="insightsのsummaryをベクトル化する")
    em.add_argument("--limit", type=int, default=500, help="1回の実行での対象件数")
    em.add_argument("--model", default=embed_mod.DEFAULT_MODEL, help="埋め込みモデル名")
    em.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    em.add_argument("--db", type=Path, default=None)

    gr = sub.add_parser("graph", help="関係グラフの操作")
    gr_sub = gr.add_subparsers(dest="graph_command", required=True)

    gr_rebuild = gr_sub.add_parser("rebuild", help="edgesを導出し直す(何度実行しても同じ結果)")
    gr_rebuild.add_argument(
        "--similarity-threshold",
        type=float,
        default=graph_mod.DEFAULT_SIMILARITY_THRESHOLD,
        help="similar_toとみなすコサイン類似度の下限",
    )
    gr_rebuild.add_argument(
        "--top-k",
        type=int,
        default=graph_mod.DEFAULT_TOP_K,
        help="1投稿から張るsimilar_toの上限",
    )
    gr_rebuild.add_argument(
        "--edge-type",
        action="append",
        choices=list(graph_mod.EDGE_TYPES),
        help="再構築する種別(既定: すべて)。複数指定可",
    )
    gr_rebuild.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    gr_rebuild.add_argument("--db", type=Path, default=None)

    se = sub.add_parser("search", help="自然言語クエリで意味検索する")
    se.add_argument("query")
    se.add_argument("--type", dest="insight_type", default=None, help="insight_typeで絞り込む")
    se.add_argument("--domain", default=None, help="domainで絞り込む")
    se.add_argument(
        "--pain-level", type=int, choices=[0, 1, 2, 3], default=None, help="pain_levelで絞り込む"
    )
    se.add_argument(
        "--monetizable", type=_bool_arg, default=None, help="monetizableで絞り込む(true/false)"
    )
    se.add_argument("--platform", choices=list(COLLECTORS), default=None, help="platformで絞り込む")
    se.add_argument("--since", type=_iso_date, default=None, help="この投稿日以降を対象にする")
    se.add_argument("--text", default=None, help="投稿本文の部分一致(全文検索)")
    se.add_argument("--limit", type=int, default=20, help="上位何件を返すか")
    se.add_argument("--model", default=embed_mod.DEFAULT_MODEL, help="埋め込みモデル名")
    se.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    se.add_argument("--db", type=Path, default=None)

    rp = sub.add_parser("report", help="決定論的な定量サマリをMarkdownで生成する")
    rp.add_argument(
        "--since", default=report_mod.DEFAULT_SINCE, help="対象期間の長さ。例: 7d(既定)"
    )
    rp.add_argument(
        "--top-n", type=int, default=report_mod.DEFAULT_TOP_N, help="頻出キーワード等の上位件数"
    )
    rp.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    rp.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    rp.add_argument("--db", type=Path, default=None)

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


def _run_extract(args: argparse.Namespace) -> int:
    extract_dir = args.data_dir / "extract"

    with connect(_db_path(args)) as conn:
        if args.extract_command == "status":
            st = extract_mod.status(conn)
            print("投稿の状態:", st["posts"])
            if st["unloaded_batches"]:
                print("未取り込みのバッチ:")
                for batch_id, created_at, count, version in st["unloaded_batches"]:
                    print(f"  {batch_id}  {count}件  {version}  作成 {created_at}")
            else:
                print("未取り込みのバッチはありません")
            if st["insights_by_domain"]:
                print("抽出済みのドメイン別件数:", dict(st["insights_by_domain"]))
            return 0

        domain_ids = load_domain_ids(args.domains)

        if args.extract_command == "prepare":
            result = extract_mod.prepare(
                conn,
                extract_dir,
                limit=args.limit,
                version=args.version,
                domain_ids=domain_ids,
                platforms=tuple(args.platform) if args.platform else DEFAULT_PLATFORMS,
                reextract=args.reextract,
                prompts_dir=args.prompts_dir,
            )
            if result is None:
                print("抽出待ちの投稿はありません")
                return 0
            print(f"バッチ {result.batch_id} を作成しました（{result.post_count}件）")
            print(f"  対象  : {result.batch_path}")
            print(f"  作業指示: {result.instruction_path}")
            print()
            print("Claude Codeセッションで作業指示のMarkdownを読ませて実行し、")
            print(f"完了後に `sns-collector extract load {result.batch_id}` を実行すること。")
            return 0

        result = extract_mod.load(
            conn, extract_dir, args.batch_id, allowed_domains=frozenset(domain_ids)
        )
        print(f"取り込み: {result.accepted}件 / 拒否: {result.rejected}件")
        if result.embeddings_cleared:
            print(f"  要約が変わったため埋め込みを破棄: {result.embeddings_cleared}件")
            print("  `sns-collector embed` を実行するまで、該当投稿は検索に出ない。")
        if result.errors_path:
            print(f"  拒否した行: {result.errors_path}")
            print("  該当投稿は batched のまま残るため、次回の再バッチで拾える。")
        return 0


def _run_keywords(args: argparse.Namespace) -> int:
    with connect(_db_path(args)) as conn:
        stats = compute_keyword_stats(conn, args.platform)

    if not stats:
        print(f"[{args.platform}] 収集済みの投稿がありません")
        return 0

    print(f"[{args.platform}] キーワード別の困りごと表現(代理指標。正式な判定は構造化抽出で行う)")
    for stat in stats:
        rate = f"{stat.pain_rate * 100:.0f}%" if stat.pain_rate is not None else "n/a"
        print(f"  {stat.keyword:40s} {stat.count:5d}件  痛み{stat.pain_count:4d}件  {rate}")
    return 0


def _run_embed(args: argparse.Namespace) -> int:
    with connect(_db_path(args)) as conn:
        result = embed_mod.embed(conn, limit=args.limit, model_name=args.model)

    if result.embedded == 0:
        print("埋め込み待ちの投稿はありません")
        return 0
    print(f"埋め込み: {result.embedded}件（モデル: {result.model}, 次元: {result.dimension}）")
    return 0


def _run_graph(args: argparse.Namespace) -> int:
    with connect(_db_path(args)) as conn:
        result = graph_mod.rebuild(
            conn,
            similarity_threshold=args.similarity_threshold,
            top_k=args.top_k,
            edge_types=tuple(args.edge_type) if args.edge_type else graph_mod.EDGE_TYPES,
        )

    print(f"edges: {result.total}件")
    for edge_type, count in result.counts.items():
        print(f"  {edge_type:12s} {count:6d}件")
    return 0


def _run_search(args: argparse.Namespace) -> int:
    with connect(_db_path(args)) as conn:
        hits = search_mod.search(
            conn,
            args.query,
            model_name=args.model,
            insight_type=args.insight_type,
            domain=args.domain,
            pain_level=args.pain_level,
            monetizable=args.monetizable,
            platform=args.platform,
            since=args.since,
            text=args.text,
            limit=args.limit,
        )

    if not hits:
        print("該当する投稿はありません（未埋め込みの投稿はヒットしない）")
        return 0

    for hit in hits:
        print(f"[{hit.score:.3f}] {hit.platform} {hit.insight_type}/{hit.domain or '-'}")
        print(f"  {hit.summary}")
        print(f"  pain_level={hit.pain_level} monetizable={hit.monetizable} {hit.url or ''}")
    return 0


def _run_report(args: argparse.Namespace) -> int:
    with connect(_db_path(args)) as conn:
        result = report_mod.generate(
            conn,
            args.reports_dir,
            since=args.since,
            top_n=args.top_n,
        )

    r = result.report
    print(f"レポート: {result.path}")
    print(f"  期間: {r.since:%Y-%m-%d} 〜 {r.until:%Y-%m-%d}")
    print(f"  最重要シグナル(pain_level=3 かつ monetizable=true): {len(r.top_signals)}件")
    if r.new_competitors:
        names = ", ".join(c.product for c in r.new_competitors)
        print(f"  新規に観測された競合製品: {names}")
    print()
    print("洞察・仮説の加筆は `prompts/report-insights.md` の作業指示を")
    print("Claude Codeセッションで実行すること。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        if args.command == "db":
            return _run_db(args)

        if args.command == "extract":
            return _run_extract(args)

        if args.command == "keywords":
            return _run_keywords(args)

        if args.command == "embed":
            return _run_embed(args)

        if args.command == "graph":
            return _run_graph(args)

        if args.command == "search":
            return _run_search(args)

        if args.command == "report":
            return _run_report(args)

        if args.command in COLLECTORS:
            module, load_config = COLLECTORS[args.command]
            module.run(
                load_config(args.keywords),
                data_dir=args.data_dir / args.command,
                db_path=_db_path(args),
            )
    except ConfigError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as e:
        # 指定ミス（存在しないプロンプト版・未登録のバッチID・引数の不整合）は
        # 利用者が直せる。トレースバックを出さず、何が足りないかだけを見せる
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except duckdb.IOException as e:
        # DuckDBはプロセス間で書き込みを排他する。cronの収集と手動実行が
        # 重なると素のトレースバックで落ちるため、次に何をすべきかを出す
        print(f"分析DBを開けなかった: {e}", file=sys.stderr)
        print("別の収集が実行中の可能性がある。終わってから再実行すること。", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
