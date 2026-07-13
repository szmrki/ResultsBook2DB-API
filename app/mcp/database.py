"""MCP サーバー用の read-only DB 接続。

既存 app/database.py と同じ SQLAlchemy による接続だが、以下が異なる:

  1. read-only 専用ロールの接続URL（DATABASE_URL_*_RO）を使う
  2. 接続時に PostgreSQL のセッションパラメータを libpq の `options` で強制する
     - default_transaction_read_only = on : 書き込みを DB レベルで禁止（主たる防御線）
     - statement_timeout                  : 長時間クエリを DB 側で打ち切る

これにより、仮に run_query 側の SQL 文字列検証を回避されても、
DB レベルで書き込み不可・時間制限ありのため堅牢。
"""

from sqlalchemy import Engine, create_engine

from app.mcp.config import (
    DATABASE_URL_FOUR_RO,
    DATABASE_URL_MD_RO,
    STATEMENT_TIMEOUT_MS,
)

# libpq の `options` パラメータに渡すセッション設定。
# `-c key=value` の形式でスペース区切りに並べると、接続確立時に SET される。
# ここで read-only とタイムアウトをセッションの初期状態として焼き込む。
_CONNECT_OPTIONS = (
    f"-c default_transaction_read_only=on -c statement_timeout={STATEMENT_TIMEOUT_MS}"
)

# connect_args は psycopg2 の接続関数にそのまま渡される。
# options に上記を指定することで、全接続が read-only + timeout 付きになる。
_CONNECT_ARGS = {"options": _CONNECT_OPTIONS}


def _make_engine(url: str) -> Engine:
    """read-only 設定を焼き込んだ SQLAlchemy エンジンを作成する。

    Args:
        url: 接続先の PostgreSQL URL（read-only ロール）。

    Returns:
        default_transaction_read_only と statement_timeout が
        セッション初期状態として設定されたエンジン。
    """
    return create_engine(url, connect_args=_CONNECT_ARGS)


# DB ごとにエンジンを1つずつ作成し、モジュール全体で使い回す。
engine_md = _make_engine(DATABASE_URL_MD_RO)
engine_four = _make_engine(DATABASE_URL_FOUR_RO)


def get_engine(db: str) -> Engine:
    """db 指定に対応する read-only エンジンを返す。

    Args:
        db: "md" または "four"。

    Returns:
        対応する SQLAlchemy エンジン。

    Raises:
        ValueError: db が "md" / "four" 以外の場合。
    """
    if db == "md":
        return engine_md
    if db == "four":
        return engine_four
    raise ValueError(f"db は 'md' または 'four' を指定してください（受け取った値: {db!r}）")
