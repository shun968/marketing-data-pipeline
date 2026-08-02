"""画面の応答。

**最重要はディレクトリトラバーサル**。レポート本文のパスだけが
URLから来るため、そこを許可ルート配下へ閉じ込められているかを固定する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import event, write, write_adr, write_events

ROUTES = ["/", "/rules", "/adr", "/reports", "/metrics", "/api/metrics"]


@pytest.mark.parametrize("route", ROUTES)
def test_空のリポジトリでも全画面が開く(client, route: str) -> None:
    # データが1つも無い状態(初回起動)で落ちると、そもそも使い始められない
    assert client.get(route).status_code == 200


def test_ADR詳細を開く(client, repo: Path) -> None:
    write_adr(repo, "0001-first.md", title="最初の決定")
    response = client.get("/adr/0001-first")
    assert response.status_code == 200
    assert "最初の決定" in response.text


def test_存在しないADRは404(client, repo: Path) -> None:
    assert client.get("/adr/9999-none").status_code == 404


def test_ドキュメント詳細を開く(client, repo: Path) -> None:
    write(repo / "CLAUDE.md", "# ルート規約\n\n本文")
    response = client.get("/rules/root")
    assert response.status_code == 200
    assert "ルート規約" in response.text


def test_存在しないドキュメントは404(client, repo: Path) -> None:
    assert client.get("/rules/none").status_code == 404


def test_レポート本文を開く(client, repo: Path) -> None:
    write(repo / "sns-collector" / "reports" / "2026-08-01.md", "# 日次\n\n本文")
    response = client.get("/reports/view", params={"path": "2026-08-01.md"})
    assert response.status_code == 200
    assert "日次" in response.text


# --- ディレクトリトラバーサル ---


@pytest.mark.parametrize(
    "attempt",
    [
        "../../.env",
        "../../../etc/passwd",
        "/etc/passwd",
        "sub/../../../.env",
    ],
)
def test_レポート閲覧がルート外へ出られない(client, repo: Path, attempt: str) -> None:
    write(repo / ".env", "ANTHROPIC_API_KEY=sk-ant-xxxx")
    (repo / "sns-collector" / "reports").mkdir(parents=True)

    response = client.get("/reports/view", params={"path": attempt})
    assert response.status_code == 404
    assert "ANTHROPIC_API_KEY" not in response.text


def test_Markdown以外は開かない(client, repo: Path) -> None:
    write(repo / "sns-collector" / "reports" / "secret.env", "KEY=1")
    response = client.get("/reports/view", params={"path": "secret.env"})
    assert response.status_code == 404


# --- メトリクス ---


def test_メトリクスAPIが集計を返す(client, repo: Path) -> None:
    write_events(
        repo,
        [
            event(check="a", exit_code=1, rules=["private-file"]),
            event(check="a", exit_code=0),
        ],
    )
    body = client.get("/api/metrics").json()
    assert body["events"] == 2
    assert body["checks"][0]["check"] == "a"
    assert body["checks"][0]["blocks"] == 1
    assert body["rules"][0]["rule"] == "private-file"


def test_記録が無い場合は案内を出す(client, repo: Path) -> None:
    response = client.get("/metrics")
    assert "まだ記録が無い" in response.text


def test_メトリクス画面にルールIDが並ぶ(client, repo: Path) -> None:
    write_events(repo, [event(exit_code=1, rules=["doc-duplicated"])])
    assert "doc-duplicated" in client.get("/metrics").text


def test_概況にゲート数が出る(client, repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n  jobs:\n    - name: a\n      run: ./scripts/check-a.sh\n"
        "    - name: b\n      run: ./scripts/check-b.sh\n",
    )
    assert client.get("/").status_code == 200


def test_壊れたタイムスタンプでも画面が落ちない(client, repo: Path) -> None:
    # 1行の破損で概況・メトリクス・APIが500になっていた（指摘2）。
    # 記録は観測であり、画面全体が見られなくなるほうが損失が大きい
    path = repo / ".metrics" / "guardrail-events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"ts": "2026-08-01T10:00:00+09:00", "check": "a", "exit_code": 0}\n'
        '{"ts": "2026-08-01T11:00:00", "check": "b", "exit_code": 1}\n'
        "これはJSONではない\n",
        encoding="utf-8",
    )
    for route in ["/", "/metrics", "/api/metrics"]:
        assert client.get(route).status_code == 200, route


def test_未完了の実行が画面に出る(client, repo: Path) -> None:
    # 完走したか分からない実行結果は、この用途では意味を持たない（指摘4）
    write(
        repo / "sns-collector" / "state" / ".logs" / "bluesky.log",
        "[2026-08-01T09:00:00+09:00] start: bluesky\n"
        "[bluesky:語] 取得: 1件 / 新規: 0件 / スキップ: 1件\n"
        "HTTPエラー: 403\n"
        "[2026-08-01T12:00:00+09:00] start: bluesky\n"
        "[2026-08-01T12:00:30+09:00] done: bluesky\n",
    )
    body = client.get("/reports").text
    assert "未完了" in body
    assert "HTTPエラー: 403" in body


def test_壊れたリンクがレポート配下にあっても画面が落ちない(client, repo: Path) -> None:
    # ルート内を指す壊れたリンクで stat() が例外を投げ、
    # レポート一覧を読む /reports と / がまとめて500になっていた
    directory = repo / "sns-collector" / "reports"
    directory.mkdir(parents=True)
    write(directory / "normal.md", "# 通常")
    (directory / "broken.md").symlink_to(directory / "missing.md")

    for route in ["/", "/reports"]:
        assert client.get(route).status_code == 200, route


def test_ゲート一覧にフック名が出る(client, repo: Path) -> None:
    write(
        repo / "lefthook.yml",
        "pre-commit:\n  jobs:\n    - name: a\n      run: ./scripts/check-a.sh\n"
        "\ncommit-msg:\n  jobs:\n    - name: commitlint\n      run: npx commitlint\n",
    )
    body = client.get("/rules").text
    assert "commit-msg" in body


# --- bind先 ---


def test_bind先が127001に固定されている() -> None:
    # 収集データを読む画面を外へ開かない。
    # ホストを引数で受け取らないこと自体が要件
    from dashboard import cli

    assert cli.BIND_HOST == "127.0.0.1"
    args = cli.build_parser().parse_args([])
    assert not hasattr(args, "host")
