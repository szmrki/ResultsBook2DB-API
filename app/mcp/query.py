"""run_query のコアロジック（クエリ実行・整形・ログ）。

MCP ツール定義（server.py）から分離し、単体でテストできるようにする。

処理の流れ:
  1. SQL 文字列検証（補助ガードレール）
  2. read-only エンジンでクエリ実行（DB 側で read-only + timeout 強制）
  3. 行数上限 + 1 件取得し、超過なら末尾を切り落として truncated=true
  4. columns + rows(値の配列) + メタ情報の dict に整形
  5. 実行内容を構造化ログに記録
"""

import time
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.logging import get_logger
from app.mcp.config import MAX_ROWS
from app.mcp.database import get_engine
from app.mcp.sql_guard import validate_readonly_query

logger = get_logger("app.mcp.query")


def _to_jsonable(value: Any) -> Any:
    """JSON 化しにくい DB の値を素直な型へ変換する。

    PostgreSQL の集計（AVG など）は Decimal を返すため float に変換する。
    その他の型（date/datetime 等）は文字列化してそのまま返す。

    Args:
        value: DB から取得したセルの値。

    Returns:
        JSON シリアライズ可能な値。
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        # Decimal はそのままだと json.dumps できないため float 化する。
        return float(value)
    # date/datetime/その他は文字列表現にフォールバックする。
    return str(value)


def run_query(sql: str, db: str) -> dict[str, Any]:
    """read-only SQL を実行し、結果を JSON 化可能な dict で返す。

    Args:
        sql: 実行する read-only SQL（SELECT / WITH で始まる単一文）。
        db: 対象DB（"md" または "four"）。

    Returns:
        以下のキーを持つ dict:
          - sql: 実行した SQL 文（再現性・引用のため）
          - db: 対象DB
          - columns: 列名のリスト
          - rows: 各行を値の配列で表したリスト
          - row_count: 返した行数（rows の長さ）
          - truncated: 行数上限を超えて切り落とした場合 True

    Raises:
        SQLValidationError: SQL が read-only の探索クエリとして不正な場合。
        ValueError: db が "md" / "four" 以外の場合。
    """
    # 1. 補助的な SQL 文字列検証（主たる防御は DB 側の read-only ロール）。
    normalized_sql = validate_readonly_query(sql)

    # 2. 対象DBの read-only エンジンを取得。
    engine = get_engine(db)

    started = time.perf_counter()
    with engine.connect() as conn:
        result = conn.execute(text(normalized_sql))
        columns = list(result.keys())

        # 3. 上限 + 1 件だけ取得する。上限ちょうどで止めず1件多く取ることで、
        #    「まだ続きがあるか（切り落としたか）」を判定できる。
        fetched = result.fetchmany(MAX_ROWS + 1)

    duration_ms = round((time.perf_counter() - started) * 1000, 1)

    truncated = len(fetched) > MAX_ROWS
    # 超過分（上限を超えた末尾）を捨てる。
    visible = fetched[:MAX_ROWS]

    # 4. 各行を JSON 化可能な値の配列へ整形する。
    rows = [[_to_jsonable(cell) for cell in row] for row in visible]

    # 5. 構造化ログに実行内容を記録する（結果の行データ自体は残さない）。
    logger.info(
        "run_query executed",
        extra={
            "db": db,
            "sql": normalized_sql,
            "row_count": len(rows),
            "truncated": truncated,
            "duration_ms": duration_ms,
        },
    )

    return {
        "sql": normalized_sql,
        "db": db,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }
