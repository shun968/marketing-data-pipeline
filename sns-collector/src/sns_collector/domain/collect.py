"""収集ユースケースが扱う形。

収集元が6つあっても、やることは「検索して、既知でないものを保存する」だけである。
違うのは *何を検索するか* と *生レスポンスをどう読むか* の2点で、
どちらも `CollectTask` に閉じ込めて adapter 側から渡す。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


class SourceUnavailable(Exception):
    """収集元へ問い合わせられなかった。

    adapter が通信例外をこれへ変換する。usecase は `requests` を知らないため、
    この形でしか失敗を受け取れない（ADR-0011の層規則）。
    """


@dataclass(frozen=True)
class Record:
    """収集した1件。`payload` はそのままJSONLへ書き、DBへも渡す。"""

    native_id: str
    payload: dict


@dataclass(frozen=True)
class CollectTask:
    """1回分の検索。

    label   ログの接頭辞。**必ず `<プラットフォーム>:<キーワード>` の形にする。**
            `dashboard/src/dashboard/sources/reports.py` の `_RESULT` が
            この2要素として解析し、キーワード単位で集計する。3要素にすると
            キーワード名に余計な文字列が混ざり、月ごとに別キーワードとして
            数えられて「新規0件のキーワード」の表が壊れる
    keyword `matched_keywords` へ記録する語。集計に使う値
    fetch   生レスポンスの列を返す。失敗時は SourceUnavailable を投げる
    parse   生レスポンス1件を Record にする。収集対象外なら None を返す
            （hnjobs が求人票以外のコメントを落とすのに使う）
    context ログ行の末尾へ添える補足（hnjobs のスレッド名など）。
            解析対象の並びより後ろに置くため、集計には影響しない
    """

    label: str
    keyword: str
    fetch: Callable[[], list[dict]]
    parse: Callable[[dict], Record | None]
    context: str | None = None


@dataclass(frozen=True)
class InsertOutcome:
    """DBへの投入結果。JSONLに在るのにDBに無い件数を必ず持ち帰る。"""

    inserted: int = 0
    failed: int = 0


@dataclass(frozen=True)
class CollectPorts:
    """usecase が外部世界へ触るための口。entrypoint が実装を結線する。

    どれもプラットフォームを引数に取らない。結線時に固定されているため、
    usecase 側が自分のプラットフォーム名を持ち回る必要がない。
    """

    known_ids: Callable[[], set[str]]
    save_records: Callable[[list[dict]], Path]
    store_records: Callable[[list[dict]], InsertOutcome]
    record_keyword_hits: Callable[[list[str], str], None]
    notify: Callable[[str], None]


@dataclass(frozen=True)
class CollectSummary:
    total_new: int = 0
    output_path: Path | None = None
    failed_labels: list[str] = field(default_factory=list)
    task_count: int = 0
