"""rb2db MCP サーバー本体。

研究室メンバーの AI ツールから、常に最新の rb2db に対して read-only SQL で
探索的分析を行えるようにする。提供するのは以下:

  ツール:
    - run_query  : 任意の read-only SQL を実行し結果を返す（探索用）
    - get_schema : DB のテーブル定義・カラムの意味・md/four 差分を返す

  リソース（全メンバーの AI が同じ前提を持つための同梱知識）:
    - rb2db://schema     : スキーマ解説
    - rb2db://sql-notes  : SQL 上の注意点（NULL 混入の罠・座標系など）
    - rb2db://metrics    : 定義済みメトリクスの定義集

起動（Streamable HTTP）:
    uv run python -m app.mcp.server

設計の詳細は memo/mcp_server_design.md を参照。
"""

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from app.logging import setup_logging
from app.mcp import knowledge
from app.mcp.config import MAX_ROWS, MCP_HOST, MCP_PORT
from app.mcp.query import run_query as _run_query
from app.mcp.sql_guard import SQLValidationError

# サーバーの説明文（instructions）。接続した AI がこのサーバーの使い方・前提を
# 把握できるよう、要点と「まず読むべきリソース」を明記する。
INSTRUCTIONS = """\
カーリング国際公式大会の実試合データベース（rb2db）に read-only SQL で問い合わせるサーバー。

DB は2系統:
- "md"   : ミックスダブルス（2人制）
- "four" : 4人制（Men / Women / Junior）

使い方:
1. まず get_schema でテーブル構造を把握する（リソース rb2db://schema も同じ内容）。
2. 分析SQLを書く前に rb2db://sql-notes を読む。特に ends 集計での NULL 除外は必須。
3. 定義済みメトリクス（ハンマー差分など）は rb2db://metrics の定義に合わせる。
4. run_query で SELECT / WITH のクエリを実行する。

制約:
- read-only のみ（SELECT / WITH で始まる単一文）。
- 返却は最大 {max_rows:,} 行。超えると truncated=true になる。
""".format(max_rows=MAX_ROWS)

# ログを初期化してからサーバーを構築する（run_query 実行時のクエリログ用）。
setup_logging()

mcp = FastMCP(
    name="rb2db",
    instructions=INSTRUCTIONS,
    host=MCP_HOST,
    port=MCP_PORT,
    # stateless_http: 各リクエストを独立処理する。SSH トンネル越しに複数メンバーが
    # つなぐ想定で、セッション状態を持たない方が素直で堅牢。
    stateless_http=True,
)


@mcp.tool()
def run_query(sql: str, db: Literal["md", "four"]) -> dict[str, Any]:
    """read-only SQL を実行し、結果を JSON で返す（探索的分析用）。

    該当する集計が定義済みメトリクス（リソース rb2db://metrics）にある場合は、
    その定義に合わせて SQL を書くこと。ends を集計する際は NULL 除外
    （score_red IS NOT NULL AND score_yellow IS NOT NULL）を必ず入れること。

    Args:
        sql: 実行する read-only SQL。SELECT または WITH で始まる単一文のみ。
        db: 対象DB。"md"（ミックスダブルス）または "four"（4人制）。

    Returns:
        以下のキーを持つ dict:
          - sql: 実行した SQL 文
          - db: 対象DB
          - columns: 列名のリスト
          - rows: 各行を値の配列で表したリスト
          - row_count: 返した行数
          - truncated: 行数上限（最大行）を超えて切り落とした場合 True
    """
    try:
        return _run_query(sql, db)
    except SQLValidationError as e:
        # 補助ガードレールでの拒否。AI が自己修正できるよう明確なメッセージを返す。
        raise ValueError(f"SQL を実行できません: {e}") from e


@mcp.tool()
def get_schema(db: Literal["md", "four"]) -> str:
    """DB のテーブル定義・カラムの意味・リレーション・md/four 差分を返す。

    Args:
        db: 対象DB。"md" または "four"。返す内容は両DB共通のスキーマ解説で、
            差分（is_power_play は md のみ 等）も本文に明記されている。

    Returns:
        スキーマ解説（Markdown 文字列）。
    """
    # スキーマは両DB共通のため、db によらず同じ解説を返す（差分は本文に明記）。
    return knowledge.load("schema.md")


# ── リソース（同梱知識） ───────────────────────────────────────────
# ツールと異なり、リソースは「AI が随時参照できる資料」として提供する。


@mcp.resource("rb2db://schema", mime_type="text/markdown")
def resource_schema() -> str:
    """スキーマ解説（テーブル構造・md/four の違い）。"""
    return knowledge.load("schema.md")


@mcp.resource("rb2db://sql-notes", mime_type="text/markdown")
def resource_sql_notes() -> str:
    """SQL 上の注意点（NULL 混入の罠・ブランクエンド定義・座標系など）。"""
    return knowledge.load("sql_notes.md")


@mcp.resource("rb2db://metrics", mime_type="text/markdown")
def resource_metrics() -> str:
    """定義済みメトリクスの定義集（ハンマー差分・スチール率など）。"""
    return knowledge.load("metrics.md")


def main() -> None:
    """Streamable HTTP トランスポートで MCP サーバーを起動する。"""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
