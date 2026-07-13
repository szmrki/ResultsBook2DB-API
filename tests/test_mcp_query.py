"""app/mcp/query.py の純粋ロジック（_to_jsonable）のテスト。

run_query 本体は DB 接続を伴うためここでは検証せず、
JSON 化のための値変換ヘルパ _to_jsonable のみをユニットテストする。
DB 由来の Decimal（AVG などの集計結果）が float に変換されることが要点。
"""

import datetime
from decimal import Decimal

from app.mcp.query import _to_jsonable


def test_basic_types_pass_through() -> None:
    """None・bool・int・float・str はそのまま返る。"""
    assert _to_jsonable(None) is None
    assert _to_jsonable(True) is True
    assert _to_jsonable(42) == 42
    assert _to_jsonable(3.14) == 3.14
    assert _to_jsonable("red") == "red"


def test_decimal_is_converted_to_float() -> None:
    """PostgreSQL の集計が返す Decimal は float に変換される。"""
    result = _to_jsonable(Decimal("0.7141202586622912"))
    assert isinstance(result, float)
    assert result == 0.7141202586622912


def test_non_json_types_fall_back_to_str() -> None:
    """date/datetime などは文字列表現にフォールバックする。"""
    d = datetime.date(2026, 7, 13)
    assert _to_jsonable(d) == "2026-07-13"
