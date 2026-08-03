"""抽出結果の検証。

抽出はLLMの出力である。スキーマ違反・存在しない post_id・範囲外の数値が
混入しうるため、**DBへ入る前に機械的に弾く**（design.md §4.3）。
ここを通ったものだけが「確定値」になる（F-06）。

検証を緩めない。緩めた分だけ下流の信頼性が落ちる。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INSIGHT_TYPES = frozenset({"need", "complaint", "advantage", "workaround", "none"})

PAIN_LEVEL_RANGE = (0, 3)
CONFIDENCE_RANGE = (0.0, 1.0)
SUMMARY_MAX = 400


class ValidationError(ValueError):
    """1行を insights の形へ落とせない。呼び出し側はこの行だけを拒否する。"""


@dataclass(frozen=True)
class Insight:
    post_id: str
    insight_type: str
    domain: str | None
    summary: str | None
    pain_level: int
    monetizable: bool
    competitors: list[str]
    confidence: float


def _require_str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} が無い、または空")
    return value.strip()


def _require_int(record: dict[str, Any], key: str, low: int, high: int) -> int:
    value = record.get(key)
    # boolはintの派生。True/False を 1/0 として通すと、型の取り違えを見逃す
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{key} が整数でない: {value!r}")
    if not low <= value <= high:
        raise ValidationError(f"{key} が範囲外({low}〜{high}): {value}")
    return value


def _require_float(record: dict[str, Any], key: str, low: float, high: float) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"{key} が数値でない: {value!r}")
    if not low <= float(value) <= high:
        raise ValidationError(f"{key} が範囲外({low}〜{high}): {value}")
    return float(value)


def validate(record: Any, *, allowed_domains: frozenset[str]) -> Insight:
    """抽出結果1行を検証して Insight にする。通らなければ ValidationError。"""
    if not isinstance(record, dict):
        raise ValidationError(f"オブジェクトでない: {type(record).__name__}")

    post_id = _require_str(record, "post_id")

    insight_type = _require_str(record, "insight_type")
    if insight_type not in INSIGHT_TYPES:
        raise ValidationError(f"insight_type が語彙外: {insight_type}")

    # domain は config/domains.yaml の統制語彙に制約する（design.md §3.2）。
    # ここを通すと、集計時に存在しない領域が現れて分類が壊れる
    domain = record.get("domain")
    if insight_type == "none":
        domain = None
    else:
        if not isinstance(domain, str) or domain not in allowed_domains:
            raise ValidationError(f"domain が統制語彙外: {domain!r}")

    summary = record.get("summary")
    if insight_type == "none":
        summary = None
    else:
        summary = _require_str(record, "summary")
        if len(summary) > SUMMARY_MAX:
            raise ValidationError(f"summary が長すぎる({len(summary)}文字 > {SUMMARY_MAX})")

    pain_level = _require_int(record, "pain_level", *PAIN_LEVEL_RANGE)
    if insight_type == "none" and pain_level != 0:
        raise ValidationError("insight_type=none なのに pain_level が0でない")

    monetizable = record.get("monetizable")
    if not isinstance(monetizable, bool):
        raise ValidationError(f"monetizable が真偽値でない: {monetizable!r}")

    competitors = record.get("competitors", [])
    if not isinstance(competitors, list) or not all(isinstance(c, str) for c in competitors):
        raise ValidationError(f"competitors が文字列の配列でない: {competitors!r}")

    confidence = _require_float(record, "confidence", *CONFIDENCE_RANGE)

    return Insight(
        post_id=post_id,
        insight_type=insight_type,
        domain=domain,
        summary=summary,
        pain_level=pain_level,
        monetizable=monetizable,
        competitors=[c.strip() for c in competitors if c.strip()],
        confidence=confidence,
    )
