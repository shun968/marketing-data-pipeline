"""キーワード改訂時の質評価（正規表現による困りごと表現の代理指標）。

Bluesky・YouTube・Hacker Newsのキーワード改訂サイクルで、同種の分析
（キーワード単位の件数・一人称の困りごと表現を含む割合）がその場限りの
スクリプトとして繰り返し書かれていた。改訂履歴（config/keywords.yaml）に
残る数値の再現性を保つため、判定ロジックを1箇所にまとめる。

**これは正式な構造化抽出の代替ではない。** `insight_type` / `pain_level` の
確定判定は `extract prepare` → Claude Codeセッション → `extract load` に委ねる
（design.md §4.3、ADR-0003）。ここでの数値は、キーワードの採否を判断する前段の
粗い代理指標に過ぎない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 型注釈のためだけに読む
    import duckdb

# Bluesky/YouTube/Hacker Newsのキーワード改訂で共通して使ってきた、
# 一人称の困りごと表現を検出する粗い代理指標（config/keywords.yaml 改訂履歴）。
PAIN_PATTERN = re.compile(
    r"\b("
    r"i tried|doesn.t work|does not work|any advice|too slow|not working|"
    r"can.t get|struggl|annoying|frustrat|failed to|keeps failing|help me|"
    r"wish there was|stuck on|no idea why"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KeywordStat:
    keyword: str
    count: int
    pain_count: int

    @property
    def pain_rate(self) -> float | None:
        return self.pain_count / self.count if self.count else None


def compute_keyword_stats(conn: duckdb.DuckDBPyConnection, platform: str) -> list[KeywordStat]:
    """プラットフォーム内の投稿を、ヒットしたキーワードごとに集計する。

    1投稿が複数キーワードにマッチしうるため、キーワード単位の件数の合計は
    投稿の総数と一致しない（`record_keyword_hits` が和集合を取るため）。
    """
    rows = conn.execute(
        "SELECT matched_keywords, text FROM posts WHERE platform = ?", [platform]
    ).fetchall()

    totals: dict[str, int] = {}
    pains: dict[str, int] = {}
    for matched_keywords, text in rows:
        pain = bool(PAIN_PATTERN.search(text or ""))
        for keyword in matched_keywords or []:
            totals[keyword] = totals.get(keyword, 0) + 1
            if pain:
                pains[keyword] = pains.get(keyword, 0) + 1

    return [
        KeywordStat(keyword=k, count=totals[k], pain_count=pains.get(k, 0))
        for k in sorted(totals, key=lambda k: -totals[k])
    ]
