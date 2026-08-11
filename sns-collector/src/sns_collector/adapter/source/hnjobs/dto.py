from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from ...text import clean_html


@dataclass(frozen=True)
class ThreadKind:
    marker: str
    authors: tuple[str, ...]


# スレッドの種別。タイトルの部分一致で判定する。
#   hiring     企業が人を探している (Ask HN: Who is hiring?)
#   freelancer 案件の発注・受注 (Ask HN: Freelancer? Seeking freelancer?)
#   hired      個人が職を探している (Ask HN: Who wants to be hired?)
# 「どこに金が動いているか」を見るのが目的なので、既定では hired を採らない
# (config/keywords.yaml の thread_kinds で選ぶ)。
#
# **主催アカウントは種別ごとに違い、引き継ぎで変わる。** 案件スレッドは
# 2025年までwhoishiring、2026年1月からjon_northが立てている(2026-08-11 実測)。
# 単一アカウントに固定すると、引き継ぎの月から静かに0件になる。
# タイトルだけで引くとAlgoliaが本文も検索し、月次スレッドは互いにリンクし合うため
# 別種別まで返る。投稿者で引いてタイトルで分類する、の両方が要る。
THREAD_KINDS = {
    "hiring": ThreadKind("Who is hiring", ("whoishiring",)),
    "freelancer": ThreadKind("Freelancer? Seeking freelancer", ("whoishiring", "jon_north")),
    "hired": ThreadKind("Who wants to be hired", ("whoishiring",)),
}


def thread_authors(kinds: list[str]) -> list[str]:
    """対象種別を立てているアカウントを重複なく列挙する(取得順を安定させる)。"""
    authors: list[str] = []
    for kind in kinds:
        for author in THREAD_KINDS[kind].authors:
            if author not in authors:
                authors.append(author)
    return authors


def thread_kind(title: str) -> str | None:
    """スレッドのタイトルから種別を決める。既知のどれでもなければ None。"""
    for kind, spec in THREAD_KINDS.items():
        if spec.marker.lower() in title.lower():
            return kind
    return None


# 案件スレッドの投稿は、冒頭でどちら側かを名乗る慣例になっている。
#   SEEKING FREELANCER 発注側（金を出す）
#   SEEKING WORK       受注側（仕事を探している）
# **両者を混ぜると金の流れを読み違える。** 2026年8月の案件スレッドはトップレベル
# 14件すべてがSEEKING WORKで、発注側は0件だった（2026-08-11 実測）。
# 名乗りは本文の先頭に置かれる。本文全体を見ると、経歴中の "seeking work" 等に
# 引っ張られるため、先頭部分だけを見る。
_SEEKING_MARKERS = (("freelancer", "SEEKING FREELANCER"), ("work", "SEEKING WORK"))
_SEEKING_SCAN_CHARS = 120


def seeking_role(body: str) -> str | None:
    """案件スレッドの投稿が発注側か受注側かを返す。名乗りが無ければ None。"""
    head = body[:_SEEKING_SCAN_CHARS].upper()
    for role, marker in _SEEKING_MARKERS:
        if marker in head:
            return role
    return None


@dataclass(frozen=True)
class HackerNewsJobPost:
    item_id: str
    keyword: str
    text: str
    thread_id: str
    thread_title: str
    thread_kind: str
    seeking: str | None
    author: str
    created_at: str
    url: str
    collected_at: str
    raw: dict[str, Any]

    @classmethod
    def from_hit(
        cls,
        hit: dict[str, Any],
        keyword: str,
        thread: dict[str, Any],
        kind: str,
        collected_at: datetime,
    ) -> HackerNewsJobPost:
        item_id = hit["objectID"]
        thread_title = thread.get("title") or ""

        # 求人票は「会社 | 職種 | 勤務地 | リモート可否 | 給与」の緩い定型だが、
        # 区切り文字も項目数も投稿者ごとに違う。ここでは分解せず本文のまま持つ。
        # 構造化は Phase 2 の抽出が担う（収集側は領域を絞ることに徹する）。
        body = clean_html(hit.get("comment_text")) or ""
        # 単体では何のスレッドの求人か分からないため、スレッド名を文脈として添える
        text = "\n".join(part for part in (thread_title, body) if part)

        return cls(
            item_id=item_id,
            keyword=keyword,
            text=text,
            thread_id=str(thread["objectID"]),
            thread_title=thread_title,
            thread_kind=kind,
            seeking=seeking_role(body),
            author=hit.get("author", ""),
            created_at=hit.get("created_at", ""),
            url=f"https://news.ycombinator.com/item?id={item_id}",
            collected_at=collected_at.isoformat(),
            # parent_id・_tags等、平坦化で落ちた情報を後から使えるように残す
            raw=hit,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def is_job_entry(hit: dict[str, Any]) -> bool:
    """スレッド直下のコメントだけを求人票とみなす。

    月次スレッドは「トップレベル = 1件の求人票、その下 = 質問・感想・議論」という
    運用で回っている。返信まで採ると「Incorrect.」のような断片が求人として
    DBに入る（2026-08-11 実測）。深さはAPIの parent_id と story_id の一致で判る。
    """
    parent_id = hit.get("parent_id")
    story_id = hit.get("story_id")
    return parent_id is not None and parent_id == story_id
