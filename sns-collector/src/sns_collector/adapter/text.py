"""収集元のレスポンスに含まれるテキストの整形。

収集元をまたいで使うため、どれか1つの `source/` に置かない。
兄弟の収集元は互いを import できない（ADR-0011）。
"""

from __future__ import annotations

import html
import re
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(value: Any) -> str | None:
    """HTML断片(<p>やHTMLエンティティ)をプレーンテキストへ。

    Hacker News（Algolia）の story_text / comment_text は投稿時のHTMLを
    そのまま含む。タグを残すと本文の判定・要約に無関係なノイズになる。
    """
    if not isinstance(value, str) or not value:
        return None
    text = html.unescape(_TAG_RE.sub("", value)).strip()
    return text or None
