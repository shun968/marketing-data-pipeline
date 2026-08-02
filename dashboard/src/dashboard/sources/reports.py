"""レポートと収集ログの読み取り。

対象は2種類。

- 生成レポート  sns-collector/reports/*.md（日次・週次の定量サマリと分析結果）
- 収集ログ      sns-collector/state/.logs/*.log（実行結果）

どちらも収集データそのものであり、gitignore配下にある。
**この画面は読むだけで、リポジトリへ書き戻さない。**

レポートはまだ生成されていない(roadmap Phase 5)。ディレクトリが無い場合も
空として扱い、生成され次第そのまま出るようにしてある。

**集計の範囲と表示の範囲を分ける。**
ログは追記され続けるため表示は直近に絞るが、集計まで絞ると
「累計」と称した値が実際の半分になる。同じ定数で両方を決めない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dashboard import markup
from dashboard.paths import OutsideRootError, relative_to_repo, resolve_within, roots

# 画面に出す実行の数。集計はこれに関係なく全行を対象にする
DISPLAY_RUNS = 20


@dataclass(frozen=True)
class Report:
    slug: str
    title: str
    path: str
    modified: str
    size: int


@dataclass(frozen=True)
class KeywordResult:
    """1キーワード分の収集結果。"""

    keyword: str
    fetched: int
    added: int
    skipped: int


@dataclass
class Run:
    """収集1回分。

    `finished` が False の実行は、開始したが `done:` を出さずに終わっている。
    このリポジトリの主要な失敗モードは途中終了(HTTPエラーで打ち切り)であり、
    完走したかどうかが分からない実行結果の画面は用をなさない。
    """

    started_at: str | None
    finished_at: str | None = None
    results: list[KeywordResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    @property
    def fetched(self) -> int:
        return sum(r.fetched for r in self.results)

    @property
    def added(self) -> int:
        return sum(r.added for r in self.results)


@dataclass(frozen=True)
class CollectorLog:
    platform: str
    path: str
    modified: str
    runs: list[Run]

    @property
    def display_runs(self) -> list[Run]:
        """画面に出す分。新しいものが先。"""
        return list(reversed(self.runs))[:DISPLAY_RUNS]

    @property
    def truncated(self) -> bool:
        return len(self.runs) > DISPLAY_RUNS

    @property
    def total_added(self) -> int:
        return sum(run.added for run in self.runs)

    @property
    def total_fetched(self) -> int:
        return sum(run.fetched for run in self.runs)

    @property
    def last_run(self) -> Run | None:
        return self.runs[-1] if self.runs else None

    @property
    def unfinished(self) -> int:
        """完走しなかった実行の数。

        最後の1回は実行中の可能性があるため除く。
        cronが3時間おきに回している以上、進行中のものを失敗として
        数えると常に1件が赤く出ることになる。
        """
        return sum(1 for run in self.runs[:-1] if not run.finished)


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _describe(directory: Path, path: Path, relative: str) -> Report | None:
    """一覧の1行を作る。読めないものは None を返す。

    **列挙と参照の間にファイルが消えうる。** 切れたシンボリックリンク、
    rglob と stat の間の削除、権限のないファイルのいずれでも
    `stat()` が例外を投げ、レポート一覧を読む `/reports` と `/` が
    まとめて500になる。1件の異常で画面全体を落とさない。
    """
    # 本文取得と同じ検証を掛ける。外を指すリンクは本文が404になるため、
    # 一覧にだけ並ぶと「開けない項目」と stat 由来の情報が残る
    try:
        resolve_within(directory, relative)
    except OutsideRootError:
        return None

    try:
        stat = path.stat()
    except OSError:
        return None

    return Report(
        slug=relative,
        title=path.stem,
        path=relative_to_repo(path),
        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        size=stat.st_size,
    )


def list_reports() -> list[Report]:
    directory = roots().reports
    if not directory.is_dir():
        return []

    items: list[Report] = []
    for path in sorted(directory.rglob("*.md"), reverse=True):
        report = _describe(directory, path, str(path.relative_to(directory)))
        if report is not None:
            items.append(report)
    return items


def read_report(slug: str) -> tuple[Report, str] | None:
    """レポート本文をHTMLで返す。

    slug はURLから来る。**必ず許可ルート配下へ解決する**
    (resolve_within が外を指すパスを弾く)。
    """
    directory = roots().reports
    path = resolve_within(directory, slug)
    if not path.is_file() or path.suffix != ".md":
        return None

    report = Report(
        slug=slug,
        title=path.stem,
        path=relative_to_repo(path),
        modified=_mtime(path),
        size=path.stat().st_size,
    )
    return report, markup.render(path.read_text(encoding="utf-8"))


_START = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*start:\s*(?P<platform>\S+)")
_DONE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s*done:\s*(?P<platform>\S+)")
_RESULT = re.compile(
    r"^\[(?P<platform>[^:\]]+):(?P<keyword>[^\]]+)\]\s*"
    r"取得:\s*(?P<fetched>\d+)件\s*/\s*新規:\s*(?P<added>\d+)件\s*/\s*スキップ:\s*(?P<skipped>\d+)件"
)


def _parse_log(text: str) -> list[Run]:
    """ログ全文を実行単位へ組み直す。

    `start:` で新しい実行が始まり、`done:` で完了する。
    どちらにも当てはまらない行は、その実行のメモとして残す。
    **落とさない。** 保存先・保存件数・エラーはここに出る
    """
    runs: list[Run] = []
    current: Run | None = None

    for line in text.splitlines():
        if not line.strip():
            continue

        start = _START.match(line)
        if start:
            current = Run(started_at=start.group("ts"))
            runs.append(current)
            continue

        if current is None:
            # ログの途中から読んだ場合、先頭に開始行が無いことがある
            current = Run(started_at=None)
            runs.append(current)

        done = _DONE.match(line)
        if done:
            current.finished_at = done.group("ts")
            continue

        result = _RESULT.match(line)
        if result:
            current.results.append(
                KeywordResult(
                    keyword=result.group("keyword"),
                    fetched=int(result.group("fetched")),
                    added=int(result.group("added")),
                    skipped=int(result.group("skipped")),
                )
            )
            continue

        current.notes.append(line)

    return runs


# パース結果のキャッシュ。キーはパス、値は (更新時刻, サイズ, 実行一覧)。
#
# 集計を全行に対して行うようにしたため、毎リクエストでログ全文を読む。
# cron_run.sh は追記のみでローテートしないので、3時間おきの実行が
# 年間で十数万行まで積み上がる。上限を設けて切り詰めると
# 「累計」が実測と食い違う問題(#27)が再発するため、
# 切り詰めではなくキャッシュで対処する。
#
# 追記されれば更新時刻とサイズが変わるので、古い結果を返し続けることはない。
_LOG_CACHE: dict[Path, tuple[float, int, list[Run]]] = {}


def _load_runs(path: Path) -> list[Run]:
    try:
        stat = path.stat()
    except OSError:
        return []

    cached = _LOG_CACHE.get(path)
    if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    runs = _parse_log(text)
    _LOG_CACHE[path] = (stat.st_mtime, stat.st_size, runs)
    return runs


def list_collector_logs() -> list[CollectorLog]:
    directory = roots().collector_logs
    if not directory.is_dir():
        return []

    logs: list[CollectorLog] = []
    for path in sorted(directory.glob("*.log")):
        # 列挙と参照の間に消えうるのはレポートと同じ
        try:
            modified = _mtime(path)
        except OSError:
            continue
        logs.append(
            CollectorLog(
                platform=path.stem,
                path=relative_to_repo(path),
                modified=modified,
                runs=_load_runs(path),
            )
        )
    return logs


def keyword_summary(logs: list[CollectorLog]) -> list[dict[str, object]]:
    """キーワード別の収集実績。

    キーワード設計の見直し(README の2原則)に使う。新規0件が続く語は
    改訂候補であり、これは事業方針側の判断材料になる。

    **全実行を対象にする。** 表示範囲で絞ると、古いログ区間にしか
    現れない語が表から消え、改訂の判断を誤らせる。
    """
    totals: dict[tuple[str, str], dict[str, int]] = {}
    for log in logs:
        for run in log.runs:
            for result in run.results:
                key = (log.platform, result.keyword)
                bucket = totals.setdefault(key, {"fetched": 0, "added": 0, "runs": 0})
                bucket["fetched"] += result.fetched
                bucket["added"] += result.added
                bucket["runs"] += 1

    rows = [
        {
            "platform": platform,
            "keyword": keyword,
            "fetched": values["fetched"],
            "added": values["added"],
            "runs": values["runs"],
        }
        for (platform, keyword), values in totals.items()
    ]
    # 新規獲得の少ない順。見直すべき語が上に来る
    rows.sort(key=lambda r: (r["added"], -r["fetched"]))
    return rows
