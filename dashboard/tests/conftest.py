"""テスト用の使い捨てリポジトリ。

実リポジトリを読むテストにすると、docs や収集ログの変更でテストが落ちる。
DASHBOARD_REPO_ROOT で読み取り先を差し替える。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DASHBOARD_REPO_ROOT", str(tmp_path))

    # lru_cache を張っているため、環境変数を変えたら捨てる
    from dashboard import paths

    paths.repo_root.cache_clear()
    yield tmp_path
    paths.repo_root.cache_clear()


@pytest.fixture
def client(repo: Path):
    from fastapi.testclient import TestClient

    from dashboard.app import create_app

    return TestClient(create_app())


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_adr(repo: Path, name: str, *, status: str = "採用", title: str = "決定") -> Path:
    return write(
        repo / "docs" / "adr" / name,
        f"""# ADR-0009: {title}

- ステータス: {status}
- 日付: 2026-08-01

## コンテキスト

背景。

## 決定

**そうする。**

## 結果

結果。
""",
    )


def write_events(repo: Path, events: list[dict]) -> Path:
    lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
    return write(repo / ".metrics" / "guardrail-events.jsonl", lines + "\n")


def event(
    *,
    ts: str = "2026-08-01T10:00:00+09:00",
    check: str = "no-private-data",
    exit_code: int = 0,
    rules: list[str] | None = None,
    duration_ms: int = 100,
    context: str = "pre-commit",
) -> dict:
    rules = rules or []
    return {
        "ts": ts,
        "check": check,
        "context": context,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "violations": len(rules),
        "rules": rules,
    }
