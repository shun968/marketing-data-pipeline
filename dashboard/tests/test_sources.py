"""データソースの読み取り。

**壊れた入力で画面が落ちないこと**を重視する。表示は検査ではない。
書式違反は scripts/check-adr-format.sh が別途止めるので、こちらは
どんな状態でも見えることを優先する。
"""

from __future__ import annotations

from pathlib import Path

from conftest import event, write, write_adr, write_events

from dashboard.sources import adr, metrics, reports, rules

# --- ADR ---


def test_ADRを読む(repo: Path) -> None:
    write_adr(repo, "0001-first.md", title="最初の決定")
    items = adr.load_all()
    assert len(items) == 1
    assert items[0].number == "0009"
    assert items[0].title == "最初の決定"
    assert items[0].is_active


def test_READMEはADRとして扱わない(repo: Path) -> None:
    write_adr(repo, "0001-first.md")
    write(repo / "docs" / "adr" / "README.md", "# 一覧")
    assert [a.slug for a in adr.load_all()] == ["0001-first"]


def test_置換済みは置換先を持つ(repo: Path) -> None:
    write_adr(repo, "0001-old.md", status="置換済み（ADR-0002）")
    item = adr.load_all()[0]
    assert item.status_key == "置換済み"
    assert item.superseded_by == "ADR-0002"
    assert not item.is_active


def test_採用が先頭で置換済みが末尾になる(repo: Path) -> None:
    write_adr(repo, "0001-superseded.md", status="置換済み（ADR-0003）")
    write_adr(repo, "0002-rejected.md", status="却下")
    write_adr(repo, "0003-active.md", status="採用")
    order = [status for status, _ in adr.group_by_status(adr.load_all())]
    assert order[0] == "採用"
    assert order[-1] == "置換済み"


def test_書式が壊れたADRでも落とさない(repo: Path) -> None:
    # 表示は検査ではない。読めるところまで読んで「不明」として出す
    write(repo / "docs" / "adr" / "0001-broken.md", "見出しが無い\n\n中身だけ")
    item = adr.load_all()[0]
    assert item.status == "不明"
    assert item.date == ""


def test_語彙外のステータスも一覧から消えない(repo: Path) -> None:
    write_adr(repo, "0001-odd.md", status="検討中")
    statuses = [status for status, _ in adr.group_by_status(adr.load_all())]
    assert "検討中" in statuses


def test_ADRが無ければ空(repo: Path) -> None:
    assert adr.load_all() == []


# --- ルール ---


def test_CLAUDEmdとスキルを集める(repo: Path) -> None:
    write(repo / "CLAUDE.md", "# ルート")
    write(repo / "sns-collector" / "CLAUDE.md", "# 領域")
    write(repo / ".claude" / "skills" / "adr" / "SKILL.md", "# 手順")
    slugs = [d.slug for d in rules.load_documents()]
    assert slugs == ["root", "area-sns-collector", "skill-adr"]


def test_lefthookからゲートを組み立てる(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n"
        "  jobs:\n"
        "    - name: no-private-data\n"
        "      run: ./scripts/record-check.sh np"
        " -- ./scripts/check-no-private-data.sh\n"
        "    - name: approval\n"
        "      interactive: true\n"
        "      run: ./scripts/check-rule-consolidation.sh\n",
    )
    gates = {g.name: g for g in rules.load_gates()}
    assert gates["no-private-data"].recorded
    assert gates["no-private-data"].script == "./scripts/check-no-private-data.sh"
    assert gates["approval"].interactive
    assert not gates["approval"].recorded


def test_記録層のラッパーは検査スクリプトとして数えない(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n  jobs:\n    - name: x\n"
        "      run: ./scripts/record-check.sh x -- ./scripts/check-doc-duplication.sh\n",
    )
    assert rules.load_gates()[0].script == "./scripts/check-doc-duplication.sh"


def test_検査でないジョブを見分ける(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n  jobs:\n    - name: tests\n      run: ./scripts/tests/run-all.sh\n",
    )
    assert not rules.load_gates()[0].is_check


def test_設定が無ければゲートも空(repo: Path) -> None:
    assert rules.load_gates() == []


# --- レポート・収集ログ ---


def test_レポートを一覧する(repo: Path) -> None:
    write(repo / "sns-collector" / "reports" / "2026-08-01.md", "# 日次")
    items = reports.list_reports()
    assert [r.slug for r in items] == ["2026-08-01.md"]


def test_レポート本文をHTMLで返す(repo: Path) -> None:
    write(repo / "sns-collector" / "reports" / "a.md", "# 見出し\n\n本文")
    found = reports.read_report("a.md")
    assert found is not None
    assert "<h1>見出し</h1>" in found[1]


def test_レポートディレクトリが無くても落ちない(repo: Path) -> None:
    # roadmap Phase 5 まで reports/ は生成されない
    assert reports.list_reports() == []


def test_収集ログを解釈する(repo: Path) -> None:
    write(
        repo / "sns-collector" / "state" / ".logs" / "bluesky.log",
        "[2026-08-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:物体検知 精度] 取得: 24件 / 新規: 3件 / スキップ: 21件\n"
        "[bluesky:顔認証 誤認識] 取得: 4件 / 新規: 0件 / スキップ: 4件\n",
    )
    log = reports.list_collector_logs()[0]
    assert log.platform == "bluesky"
    assert log.total_fetched == 28
    assert log.total_added == 3
    assert log.last_run == "2026-08-01T09:00:00+09:00"


def test_解釈できないログ行も落とさない(repo: Path) -> None:
    write(repo / "sns-collector" / "state" / ".logs" / "x.log", "想定外の行\n")
    log = reports.list_collector_logs()[0]
    assert len(log.entries) == 1
    assert log.entries[0].keyword is None


def test_キーワード実績は新規の少ない順(repo: Path) -> None:
    # 新規0件が続く語は改訂候補。上に来ないと見直しに使えない
    write(
        repo / "sns-collector" / "state" / ".logs" / "bluesky.log",
        "[2026-08-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:よく当たる] 取得: 10件 / 新規: 5件 / スキップ: 5件\n"
        "[bluesky:空振り] 取得: 30件 / 新規: 0件 / スキップ: 30件\n",
    )
    rows = reports.keyword_summary(reports.list_collector_logs())
    assert rows[0]["keyword"] == "空振り"
    assert rows[0]["added"] == 0


# --- メトリクス ---


def test_イベントが無ければ空(repo: Path) -> None:
    assert metrics.load_events() == []


def test_検査ごとに集計する(repo: Path) -> None:
    write_events(
        repo,
        [
            event(check="a", exit_code=0, duration_ms=100),
            event(check="a", exit_code=1, rules=["r1"], duration_ms=300),
            event(check="b", exit_code=0, duration_ms=50),
        ],
    )
    stats = {s.check: s for s in metrics.check_stats(metrics.load_events())}
    assert stats["a"].runs == 2
    assert stats["a"].blocks == 1
    assert stats["a"].avg_ms == 200
    assert stats["b"].blocks == 0


def test_ブロックの多い検査が先頭に来る(repo: Path) -> None:
    write_events(
        repo,
        [
            event(check="quiet", exit_code=0),
            event(check="noisy", exit_code=1, rules=["r"]),
            event(check="noisy", exit_code=1, rules=["r"]),
        ],
    )
    assert metrics.check_stats(metrics.load_events())[0].check == "noisy"


def test_ルール別に数える(repo: Path) -> None:
    write_events(
        repo,
        [
            event(rules=["private-file"], exit_code=1),
            event(rules=["private-file", "secret-string"], exit_code=1),
        ],
    )
    rows = {r.rule: r.hits for r in metrics.rule_stats(metrics.load_events())}
    assert rows == {"private-file": 2, "secret-string": 1}


def test_一度も止めていない検査を候補に出す(repo: Path) -> None:
    write_events(
        repo,
        [event(check="quiet", exit_code=0), event(check="loud", exit_code=1, rules=["r"])],
    )
    stats = metrics.check_stats(metrics.load_events())
    assert [s.check for s in metrics.silent_checks(stats)] == ["quiet"]


def test_壊れた行を飛ばして読み進める(repo: Path) -> None:
    # 記録は観測であって、1行の破損で画面全体が見られなくなるほうが損失が大きい
    path = repo / ".metrics" / "guardrail-events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"ts": "2026-08-01T10:00:00+09:00", "check": "a", "exit_code": 0}\n'
        "これはJSONではない\n"
        '{"欠けている": "キー"}\n'
        '{"ts": "2026-08-01T11:00:00+09:00", "check": "b", "exit_code": 1}\n',
        encoding="utf-8",
    )
    events = metrics.load_events()
    assert [e.check for e in events] == ["a", "b"]


def test_日別の推移は日付順に並ぶ(repo: Path) -> None:
    write_events(
        repo,
        [
            event(ts="2026-08-01T10:00:00+09:00", exit_code=1, rules=["r"]),
            event(ts="2026-08-03T10:00:00+09:00", exit_code=0),
        ],
    )
    daily = metrics.daily_counts(metrics.load_events(), days=3)
    assert [d["date"] for d in daily] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert daily[0]["blocks"] == 1
    assert daily[1]["runs"] == 0
