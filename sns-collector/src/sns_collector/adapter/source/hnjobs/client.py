from __future__ import annotations

from typing import Any

from ...http import get_json

# hackernews/client.py と同じAlgoliaの非公式API。役割が違うため別モジュールにする。
# あちらは「キーワードで全文検索」、こちらは「特定スレッドの中だけを検索」。
LIST_URL = "https://hn.algolia.com/api/v1/search_by_date"
SEARCH_URL = "https://hn.algolia.com/api/v1/search"

# Algoliaは既定でタイプミスを吸収し、短い語ほど別語へ広がる。
# "cnc" は2026年8月の求人スレッドで13件ヒットしたが、中身は不動産・請負業者の
# マッチングサービス等で1件も工作機械と関係が無かった。無効化すると0件になる。
# **求人票は1件が長く、誤検知は「無関係な会社をその領域の求人として数える」形で
# 効く**（件数を見て領域の厚みを判断するため、そのまま結論が歪む）。
# APIの性質であって利用者の設定ではないため、keywords.yamlへは出さない。
TYPO_TOLERANCE = "false"


def list_threads(author: str, hits_per_page: int) -> list[dict[str, Any]]:
    """月次スレッドの主催アカウントの投稿を新着順に取得する。1ページのみ。

    タイトルの全文検索(query="Ask HN: Who is hiring?")では
    「Show HN: HN Hiring - Search and Filter Who Is Hiring」のような別人の
    関連スレッドが混ざる(2026-08-11 実測)。投稿者で引けば混ざらない。
    どのアカウントが対象かは hnjobs/models.py の THREAD_KINDS が持つ。
    """
    payload = get_json(
        LIST_URL,
        params={"tags": f"story,author_{author}", "hitsPerPage": hits_per_page},
        label=f"hnjobs:threads:{author}",
    )
    # "hits"キー自体がnullで返る余地がある。`.get("hits", [])`はキーが存在して
    # nullのとき既定値を使わず、呼び出し側のforがTypeErrorで落ちる（github/client.py
    # と同じ失敗モード）。RequestExceptionの隔離をすり抜けてrun全体が止まる
    return payload.get("hits") or []


def search_thread(story_id: str, query: str, hits_per_page: int) -> list[dict[str, Any]]:
    """1スレッドの中をキーワードで検索する。1ページのみ(ページングはしない)。

    絞り込みをAPI側へ寄せている。スレッドは1本あたり300〜600コメントあり、
    全件取ってからローカルで絞ると1スレッドにつき数十リクエストになる。
    """
    payload = get_json(
        SEARCH_URL,
        params={
            "query": query,
            "tags": f"comment,story_{story_id}",
            "hitsPerPage": hits_per_page,
            "typoTolerance": TYPO_TOLERANCE,
        },
        label=f"hnjobs:{story_id}:{query}",
    )
    # "hits"キー自体がnullで返る余地がある。`.get("hits", [])`はキーが存在して
    # nullのとき既定値を使わず、呼び出し側のforがTypeErrorで落ちる（github/client.py
    # と同じ失敗モード）。RequestExceptionの隔離をすり抜けてrun全体が止まる
    return payload.get("hits") or []
