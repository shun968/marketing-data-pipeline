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


# 指摘3の回帰。「どこで動くか」を出す画面なので、フックを取り違えると
# 目的そのものが崩れる
def test_フックごとに実行場所を出し分ける(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n"
        "  jobs:\n"
        "    - name: no-private-data\n"
        "      run: ./scripts/check-no-private-data.sh\n"
        "\n"
        "prepare-commit-msg:\n"
        "  jobs:\n"
        "    - name: suggest-commit-msg\n"
        "      run: ./scripts/suggest-commit-msg.sh {1}\n"
        "\n"
        "commit-msg:\n"
        "  parallel: true\n"
        "  jobs:\n"
        "    - name: commitlint\n"
        "      run: npx --no -- commitlint --edit {1}\n",
    )
    where = {g.name: g.where for g in rules.load_gates()}
    assert where == {
        "no-private-data": "pre-commit",
        "suggest-commit-msg": "prepare-commit-msg",
        "commitlint": "commit-msg",
    }


# 2周目の指摘。名前を持たないジョブが2つ以上並ぶと、2つ目以降が
# 現在のジョブへ吸収されて消え、interactive も前のゲートへ漏れていた。
# 名前つきの経路だけを直しても、この経路には残る
def test_名前を持たないジョブが2つ以上でも消えない(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n"
        "  jobs:\n"
        "    - run: ./scripts/check-a.sh\n"
        "    - run: ./scripts/check-b.sh\n"
        "      interactive: true\n",
    )
    gates = rules.load_gates()
    assert [g.command for g in gates] == ["./scripts/check-a.sh", "./scripts/check-b.sh"]
    # 印は2つ目のジョブのもの。前へ漏らさない
    assert [g.interactive for g in gates] == [False, True]


def test_名前を持たないジョブはコマンドを名前にする(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n  jobs:\n    - run: ./scripts/check-a.sh\n",
    )
    assert rules.load_gates()[0].name == "./scripts/check-a.sh"


# 2周目の指摘。`\S+` だと空白入りの名前がジョブの境界にならず、
# 名前がコマンドで置き換わったうえ、2つ並ぶと片方が消えていた
def test_空白を含むジョブ名を扱える(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n"
        "  jobs:\n"
        "    - name: check scripts\n"
        "      run: ./scripts/check-a.sh\n"
        "    - name: lint yaml\n"
        "      run: ./scripts/lint-b.sh\n",
    )
    gates = rules.load_gates()
    assert [g.name for g in gates] == ["check scripts", "lint yaml"]
    assert [g.script for g in gates] == ["./scripts/check-a.sh", "./scripts/lint-b.sh"]


def test_承認フローの印が次のジョブへ漏れない(repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n"
        "  jobs:\n"
        "    - name: approval\n"
        "      interactive: true\n"
        "      run: ./scripts/check-rule-consolidation.sh\n"
        "    - name: plain\n"
        "      run: ./scripts/check-doc-duplication.sh\n",
    )
    gates = {g.name: g for g in rules.load_gates()}
    assert gates["approval"].interactive
    assert not gates["plain"].interactive


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


def test_収集ログを実行単位へ組み直す(repo: Path) -> None:
    write(
        repo / "sns-collector" / "state" / ".logs" / "bluesky.log",
        "[2026-08-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:物体検知 精度] 取得: 24件 / 新規: 3件 / スキップ: 21件\n"
        "[bluesky:顔認証 誤認識] 取得: 4件 / 新規: 0件 / スキップ: 4件\n"
        "[2026-08-01T09:00:30+09:00] done: bluesky\n",
    )
    log = reports.list_collector_logs()[0]
    assert log.platform == "bluesky"
    assert len(log.runs) == 1
    assert log.total_fetched == 28
    assert log.total_added == 3
    assert log.last_run.started_at == "2026-08-01T09:00:00+09:00"
    assert log.last_run.finished


# 指摘1の回帰。表示の切り詰めと集計の範囲を同じ定数で決めると、
# 「累計」と称した値が実測で半分になった（bluesky 11,658 → 5,742）
def test_集計は表示範囲に切り詰められない(repo: Path) -> None:
    runs = []
    for index in range(reports.DISPLAY_RUNS + 10):
        runs.append(
            f"[2026-08-01T{index % 24:02d}:00:00+09:00] start: bluesky\n"
            "[bluesky:語] 取得: 10件 / 新規: 1件 / スキップ: 9件\n"
            f"[2026-08-01T{index % 24:02d}:00:30+09:00] done: bluesky\n"
        )
    write(repo / "sns-collector" / "state" / ".logs" / "bluesky.log", "".join(runs))

    log = reports.list_collector_logs()[0]
    total = reports.DISPLAY_RUNS + 10
    assert len(log.runs) == total
    assert log.total_fetched == total * 10
    assert log.total_added == total
    # 画面に出すのは直近のみ。集計とは別
    assert len(log.display_runs) == reports.DISPLAY_RUNS
    assert log.truncated


def test_キーワード実績も表示範囲に切り詰められない(repo: Path) -> None:
    # 古いログ区間にしか出ない語が表から消えると、改訂の判断を誤る
    old_runs = (
        "[2026-07-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:古い語] 取得: 5件 / 新規: 0件 / スキップ: 5件\n"
        "[2026-07-01T09:00:30+09:00] done: bluesky\n"
    )
    recent = "".join(
        f"[2026-08-01T{i % 24:02d}:00:00+09:00] start: bluesky\n"
        "[bluesky:新しい語] 取得: 1件 / 新規: 1件 / スキップ: 0件\n"
        f"[2026-08-01T{i % 24:02d}:00:30+09:00] done: bluesky\n"
        for i in range(reports.DISPLAY_RUNS + 5)
    )
    write(repo / "sns-collector" / "state" / ".logs" / "bluesky.log", old_runs + recent)

    keywords = {row["keyword"] for row in reports.keyword_summary(reports.list_collector_logs())}
    assert "古い語" in keywords


# 指摘4の回帰。このリポジトリの主要な失敗モードは途中終了であり、
# 完走したかどうかが分からない実行結果の画面は用をなさない
def test_途中で終わった実行を見分ける(repo: Path) -> None:
    write(
        repo / "sns-collector" / "state" / ".logs" / "bluesky.log",
        "[2026-08-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:語A] 取得: 10件 / 新規: 2件 / スキップ: 8件\n"
        "HTTPエラー: 403\n"
        "[2026-08-01T12:00:00+09:00] start: bluesky\n"
        "[bluesky:語B] 取得: 5件 / 新規: 1件 / スキップ: 4件\n"
        "[2026-08-01T12:00:30+09:00] done: bluesky\n",
    )
    log = reports.list_collector_logs()[0]
    assert len(log.runs) == 2
    assert not log.runs[0].finished
    assert log.runs[1].finished
    assert log.unfinished == 1


def test_実行中の最後の1回は未完走に数えない(repo: Path) -> None:
    # cronが回っている以上、進行中を失敗として数えると常に1件赤くなる
    write(
        repo / "sns-collector" / "state" / ".logs" / "bluesky.log",
        "[2026-08-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:語] 取得: 1件 / 新規: 0件 / スキップ: 1件\n",
    )
    log = reports.list_collector_logs()[0]
    assert not log.last_run.finished
    assert log.unfinished == 0


# 指摘4の回帰。保存件数・保存先・エラーはここにしか出ない
def test_キーワード行以外のログも落とさない(repo: Path) -> None:
    write(
        repo / "sns-collector" / "state" / ".logs" / "youtube.log",
        "[2026-08-01T09:00:00+09:00] start: youtube\n"
        "[youtube:語] 取得: 3件 / 新規: 1件 / スキップ: 2件\n"
        "合計 1 件を data/youtube/2026-08-01.jsonl に保存しました。\n"
        "[2026-08-01T09:00:30+09:00] done: youtube\n",
    )
    run = reports.list_collector_logs()[0].runs[0]
    assert run.notes == ["合計 1 件を data/youtube/2026-08-01.jsonl に保存しました。"]


def test_開始行が無いログでも落とさない(repo: Path) -> None:
    # ログの途中から読んだ場合、先頭に start: が無い
    write(repo / "sns-collector" / "state" / ".logs" / "x.log", "想定外の行\n")
    log = reports.list_collector_logs()[0]
    assert len(log.runs) == 1
    assert log.runs[0].started_at is None
    assert log.runs[0].notes == ["想定外の行"]


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


# 2周目の指摘。resolve_within はルート外を弾くが、ルート内を指す
# 壊れたリンクは通す。その後の stat() が例外を投げ、
# レポート一覧を読む /reports と / がまとめて500になっていた
def test_ルート内で切れたリンクがあっても一覧が壊れない(repo: Path) -> None:
    directory = repo / "sns-collector" / "reports"
    directory.mkdir(parents=True)
    write(directory / "normal.md", "# 通常")
    (directory / "broken.md").symlink_to(directory / "missing.md")

    assert [r.slug for r in reports.list_reports()] == ["normal.md"]


def test_収集ログが消えても一覧が壊れない(repo: Path) -> None:
    directory = repo / "sns-collector" / "state" / ".logs"
    directory.mkdir(parents=True)
    (directory / "dangling.log").symlink_to(directory / "missing.log")
    write(directory / "ok.log", "[2026-08-01T09:00:00+09:00] start: ok\n")

    assert [log.platform for log in reports.list_collector_logs()] == ["ok"]


# 2周目の指摘。集計を全行にしたため毎リクエストで全文を読む。
# cron_run.sh は追記のみでローテートしないため、上限が無い
def test_ログのパース結果を再利用する(repo: Path) -> None:
    path = repo / "sns-collector" / "state" / ".logs" / "x.log"
    write(
        path,
        "[2026-08-01T09:00:00+09:00] start: x\n"
        "[x:語] 取得: 1件 / 新規: 0件 / スキップ: 1件\n"
        "[2026-08-01T09:00:30+09:00] done: x\n",
    )
    first = reports.list_collector_logs()[0].runs
    second = reports.list_collector_logs()[0].runs
    assert first is second


def test_追記されたログは読み直す(repo: Path) -> None:
    # キャッシュが古い結果を返し続けると、収集が止まったように見える
    path = repo / "sns-collector" / "state" / ".logs" / "x.log"
    write(path, "[2026-08-01T09:00:00+09:00] start: x\n")
    assert len(reports.list_collector_logs()[0].runs) == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write("[2026-08-01T12:00:00+09:00] start: x\n")
    assert len(reports.list_collector_logs()[0].runs) == 2


# 指摘6の回帰。本文は404で拒否されるので、一覧にだけ残ると
# 「開けない項目」と stat 由来のサイズ・更新時刻が出る
def test_ルート外を指すレポートは一覧にも出さない(repo: Path) -> None:
    secret = write(repo / "secret.md", "APIキー")
    directory = repo / "sns-collector" / "reports"
    directory.mkdir(parents=True)
    (directory / "link.md").symlink_to(secret)
    write(directory / "normal.md", "# 通常")

    assert [r.slug for r in reports.list_reports()] == ["normal.md"]


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


# 指摘2の回帰。sort が try の外にあり、naive と aware の比較で
# TypeError が伝播して概況・メトリクス・APIが500になっていた
def test_タイムゾーンなしのtsが混ざっても落ちない(repo: Path) -> None:
    path = repo / ".metrics" / "guardrail-events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"ts": "2026-08-01T10:00:00+09:00", "check": "aware", "exit_code": 0}\n'
        '{"ts": "2026-08-01T11:00:00", "check": "naive", "exit_code": 1}\n',
        encoding="utf-8",
    )
    events = metrics.load_events()
    assert {e.check for e in events} == {"aware", "naive"}
    assert all(e.ts.tzinfo is not None for e in events)


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
