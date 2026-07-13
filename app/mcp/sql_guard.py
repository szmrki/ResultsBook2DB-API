"""run_query の SQL 文字列検証（補助的なガードレール）。

設計方針（memo/mcp_server_design.md §4.1）:
  主たる防御線は DB 側（read-only ロール + default_transaction_read_only）。
  ここでの文字列検証は「補助」であり、目的は書き込みの完全防止ではなく、
  明らかに不正なSQLを実行前に分かりやすいエラーで弾くこと。
  そのため、正規表現でキーワードを網羅的に禁止するような、
  回避されやすく誤検知も多い方式は取らない。

チェック内容:
  1. 空でないこと
  2. コメント除去後、先頭のキーワードが SELECT または WITH であること
  3. 複数文でないこと（末尾以外にセミコロンが無いこと）
"""

import re


class SQLValidationError(ValueError):
    """SQL が read-only の探索クエリとして受け付けられない場合に送出される。"""


# 行コメント（-- 以降）とブロックコメント（/* ... */）を取り除くための正規表現。
# コメントに紛れ込ませた別文やキーワードで判定を誤らせないよう、先に除去する。
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(sql: str) -> str:
    """SQL からコメントを除去する。

    Args:
        sql: 元のSQL文字列。

    Returns:
        行コメント・ブロックコメントを取り除いた文字列。
    """
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    return sql


def validate_readonly_query(sql: str) -> str:
    """探索用の read-only クエリとして妥当かを検証する。

    Args:
        sql: 実行しようとしている SQL 文字列。

    Returns:
        前後の空白を除去した SQL 文字列（実行に使う正規化済みの形）。

    Raises:
        SQLValidationError: 空、SELECT/WITH 以外で始まる、または複数文の場合。
    """
    if not sql or not sql.strip():
        raise SQLValidationError("SQL が空です。")

    # コメントを除いた本体で判定する。
    body = _strip_comments(sql).strip()
    if not body:
        raise SQLValidationError("SQL にコメント以外の内容がありません。")

    # 複数文の禁止: 末尾のセミコロンは許容し、それ以外の位置にあれば複数文とみなす。
    # 文字列リテラル内のセミコロンまでは厳密に見ないが、これは「補助」チェックであり、
    # 万一すり抜けても read-only ロールが書き込みを防ぐ。
    stripped_trailing = body.rstrip().rstrip(";").rstrip()
    if ";" in stripped_trailing:
        raise SQLValidationError(
            "複数の SQL 文は実行できません。1つの SELECT / WITH クエリのみ指定してください。"
        )

    # 先頭キーワードが SELECT または WITH であること（大文字小文字は無視）。
    first_word = body.split(None, 1)[0].upper()
    if first_word not in ("SELECT", "WITH"):
        raise SQLValidationError(
            "read-only の探索クエリのみ実行できます。"
            "SELECT または WITH で始まるクエリを指定してください。"
            f"（受け取った先頭キーワード: {first_word}）"
        )

    return sql.strip()
