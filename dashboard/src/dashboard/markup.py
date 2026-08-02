"""MarkdownをHTMLへ変換する。

外部CDNを一切参照しない。この画面は収集データを読むためローカルに閉じており、
描画のために外部へリクエストを飛ばすと、その前提が崩れる。
"""

from __future__ import annotations

from functools import lru_cache

from markdown_it import MarkdownIt


@lru_cache(maxsize=1)
def _renderer() -> MarkdownIt:
    # commonmark には表が含まれない。規約表・ADRの表が本文の中心なので有効化する
    md = MarkdownIt("commonmark", {"html": False, "linkify": False})
    md.enable("table")
    md.enable("strikethrough")
    return md


def render(text: str) -> str:
    """MarkdownをHTMLへ変換する。

    `html: False` により生HTMLはエスケープされる。ドキュメントは自分で
    書いたものだが、レンダラの設定でXSSの有無が変わる箇所を暗黙にしない。
    """
    return _renderer().render(text)
