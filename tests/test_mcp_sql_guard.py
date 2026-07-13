"""app/mcp/sql_guard.py（run_query の補助的な SQL 検証）のテスト。

sql_guard は DB にも環境変数にも依存しない純粋なロジックなので、
そのまま import してユニットテストできる。

確認すること:
  1. SELECT / WITH で始まる単一文は受理し、前後空白を除去して返す
  2. 空・コメントのみ・書き込み文・複数文は SQLValidationError で弾く
"""

import pytest

from app.mcp.sql_guard import SQLValidationError, validate_readonly_query


# ── 正常系: 受理されるべきSQLと、正規化後の期待値 ──────────────────────
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", "SELECT 1"),
        # 前後の空白は除去される
        ("  select * from ends  ", "select * from ends"),
        # 大文字小文字は問わない
        ("with t as (select 1) select * from t", "with t as (select 1) select * from t"),
        # 末尾のセミコロンは許容（複数文とはみなさない）
        ("SELECT 1;", "SELECT 1;"),
        # 行コメントが付いていても本体が SELECT なら受理
        ("SELECT 1 -- コメント", "SELECT 1 -- コメント"),
    ],
)
def test_valid_queries_are_accepted(sql: str, expected: str) -> None:
    """SELECT / WITH で始まる単一文は受理され、正規化されて返る。"""
    assert validate_readonly_query(sql) == expected


# ── 異常系: 弾かれるべきSQL ────────────────────────────────────────────
@pytest.mark.parametrize(
    "sql",
    [
        "",  # 空文字
        "   ",  # 空白のみ
        "-- コメントだけ",  # 実体がコメントのみ
        "/* ブロック */",  # ブロックコメントのみ
        "DELETE FROM ends",  # 書き込み系
        "UPDATE ends SET score_red = 0",
        "INSERT INTO ends VALUES (1)",
        "DROP TABLE ends",
        "SELECT 1; DROP TABLE ends",  # 複数文（末尾以外にセミコロン）
    ],
)
def test_invalid_queries_are_rejected(sql: str) -> None:
    """空・コメントのみ・書き込み・複数文は SQLValidationError で弾かれる。"""
    with pytest.raises(SQLValidationError):
        validate_readonly_query(sql)


def test_comment_hiding_write_statement_is_rejected() -> None:
    """コメントで先頭を偽装しても、本体の先頭キーワードで判定される。"""
    # 先頭のコメントを剥がすと DELETE が本体になるため弾かれる。
    with pytest.raises(SQLValidationError):
        validate_readonly_query("-- SELECT\nDELETE FROM ends")
