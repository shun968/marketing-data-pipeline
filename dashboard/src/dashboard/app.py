"""モニタリング画面のASGIアプリ。

**127.0.0.1 以外へbindしない。** この画面は収集データ(投稿本文を含む
レポート、収集ログ)を読む。bind先の決定は cli.py 側にあり、
そこでテストによって固定している。

常駐サーバにしているのは、リロードのたびにファイルを読み直して
最新の状態を出すため。ビルド成果物を作らないので、生成物が
誤ってコミットされる経路も生まれない。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.paths import OutsideRootError, repo_root, roots
from dashboard.sources import adr, metrics, reports, rules

_HERE = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    app = FastAPI(title="marketing-data-pipeline モニタリング", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    def page(request: Request, name: str, **context: object) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=name,
            context={"repo_root": str(repo_root()), **context},
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        events = metrics.load_events()
        stats = metrics.check_stats(events)
        adrs = adr.load_all()
        logs = reports.list_collector_logs()
        return page(
            request,
            "index.html",
            nav="overview",
            adr_total=len(adrs),
            adr_active=sum(1 for a in adrs if a.is_active),
            gate_count=len(rules.load_gates()),
            report_count=len(reports.list_reports()),
            log_count=len(logs),
            collected=sum(log.total_added for log in logs),
            events_total=len(events),
            blocks_total=sum(1 for e in events if e.blocked),
            top_rules=metrics.rule_stats(events)[:5],
            silent=metrics.silent_checks(stats),
            has_metrics=metrics.events_path().is_file(),
        )

    @app.get("/rules", response_class=HTMLResponse)
    def rules_page(request: Request) -> HTMLResponse:
        documents = rules.load_documents()
        return page(
            request,
            "rules.html",
            nav="rules",
            documents=documents,
            gates=rules.load_gates(),
            selected=None,
        )

    @app.get("/rules/{slug}", response_class=HTMLResponse)
    def rule_detail(request: Request, slug: str) -> HTMLResponse:
        documents = rules.load_documents()
        selected = next((d for d in documents if d.slug == slug), None)
        if selected is None:
            raise HTTPException(status_code=404, detail="該当するドキュメントが無い")
        return page(
            request,
            "rules.html",
            nav="rules",
            documents=documents,
            gates=rules.load_gates(),
            selected=selected,
        )

    @app.get("/adr", response_class=HTMLResponse)
    def adr_index(request: Request) -> HTMLResponse:
        items = adr.load_all()
        return page(
            request,
            "adr.html",
            nav="adr",
            groups=adr.group_by_status(items),
            total=len(items),
            selected=None,
            body_html=None,
        )

    @app.get("/adr/{slug}", response_class=HTMLResponse)
    def adr_detail(request: Request, slug: str) -> HTMLResponse:
        items = adr.load_all()
        selected = next((a for a in items if a.slug == slug), None)
        if selected is None:
            raise HTTPException(status_code=404, detail="該当するADRが無い")
        return page(
            request,
            "adr.html",
            nav="adr",
            groups=adr.group_by_status(items),
            total=len(items),
            selected=selected,
            body_html=adr.render_body(selected),
        )

    @app.get("/reports", response_class=HTMLResponse)
    def reports_index(request: Request) -> HTMLResponse:
        logs = reports.list_collector_logs()
        return page(
            request,
            "reports.html",
            nav="reports",
            reports=reports.list_reports(),
            logs=logs,
            keywords=reports.keyword_summary(logs),
            reports_dir=str(roots().reports),
            selected=None,
            body_html=None,
        )

    @app.get("/reports/view", response_class=HTMLResponse)
    def report_detail(request: Request, path: str) -> HTMLResponse:
        # path はクエリ文字列から来る。許可ルートの外を指していたら
        # 404 にする。存在の有無を漏らさないため 403 とは区別しない
        try:
            found = reports.read_report(path)
        except OutsideRootError:
            raise HTTPException(status_code=404, detail="該当するレポートが無い") from None
        if found is None:
            raise HTTPException(status_code=404, detail="該当するレポートが無い")

        report, body_html = found
        logs = reports.list_collector_logs()
        return page(
            request,
            "reports.html",
            nav="reports",
            reports=reports.list_reports(),
            logs=logs,
            keywords=reports.keyword_summary(logs),
            reports_dir=str(roots().reports),
            selected=report,
            body_html=body_html,
        )

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics_page(request: Request) -> HTMLResponse:
        events = metrics.load_events()
        stats = metrics.check_stats(events)
        return page(
            request,
            "metrics.html",
            nav="metrics",
            events_total=len(events),
            checks=stats,
            rule_rows=metrics.rule_stats(events),
            daily=metrics.daily_counts(events),
            silent=metrics.silent_checks(stats),
            gates=rules.load_gates(),
            events_file=str(metrics.events_path()),
            has_metrics=metrics.events_path().is_file(),
        )

    @app.get("/api/metrics")
    def metrics_api() -> JSONResponse:
        """集計結果のJSON。手元で別の切り口を試すとき用。"""
        events = metrics.load_events()
        stats = metrics.check_stats(events)
        return JSONResponse(
            {
                "events": len(events),
                "checks": [
                    {
                        "check": s.check,
                        "runs": s.runs,
                        "blocks": s.blocks,
                        "violations": s.violations,
                        "avg_ms": s.avg_ms,
                    }
                    for s in stats
                ],
                "rules": [
                    {"rule": r.rule, "hits": r.hits, "last_seen": r.last_seen}
                    for r in metrics.rule_stats(events)
                ],
                "daily": metrics.daily_counts(events),
            }
        )

    return app
