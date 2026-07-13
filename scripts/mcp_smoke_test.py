"""scripts/mcp_smoke_test.py

起動中の rb2db MCP サーバーに対するスモークテスト（疎通・基本動作の確認）。

本番へデプロイする前に、ローカル（開発環境）で MCP サーバーが正しく動くことを
一括で確認するためのスクリプト。Streamable HTTP で接続し、以下を順に確認する:

  1. ツール一覧・リソース一覧が期待通り登録されているか
  2. get_schema がスキーマ解説を返すか
  3. run_query で集計クエリ（ハンマー差分）が計算できるか
  4. 行数上限を超えるクエリで truncated=true になるか
  5. 書き込みSQL（DELETE）が拒否されるか（read-only 保証）
  6. リソース（rb2db://sql-notes）が読めるか

使い方:
  # db と mcp を起動しておく
  docker compose up -d db mcp

  # デフォルト（http://localhost:8100/mcp）に対して実行
  uv run python scripts/mcp_smoke_test.py

  # 接続先を変えたい場合は環境変数で上書き
  MCP_URL=http://localhost:8100/mcp uv run python scripts/mcp_smoke_test.py

前提:
  MCP サーバーが起動しており、read-only ロールで DB に接続できること
  （「MCP サーバーの初回セットアップ」でロールを作成済みであること）。
"""

import asyncio
import json
import os

# mcp SDK のクライアント側 API。Streamable HTTP トランスポートで接続する。
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 接続先URL。環境変数 MCP_URL で上書きできる（デフォルトはローカルのトンネル先）。
MCP_URL = os.getenv("MCP_URL", "http://localhost:8100/mcp")


async def run_checks() -> None:
    """MCP サーバーに接続し、一連のスモークチェックを実行する。

    各チェックの結果を標準出力に出す。失敗（想定と異なる挙動）があれば
    その場で分かるよう、要点を print する。
    """
    # streamablehttp_client はコネクションを開き、読み書き用のストリームを返す。
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        # ClientSession は MCP プロトコル（initialize / tools 呼び出し等）を担う。
        async with ClientSession(read, write) as session:
            # ハンドシェイク。サーバーの capabilities を受け取る。
            await session.initialize()

            # ── 1. ツール・リソース一覧 ──
            tools = await session.list_tools()
            print("TOOLS    :", [t.name for t in tools.tools])
            resources = await session.list_resources()
            print("RESOURCES:", [str(r.uri) for r in resources.resources])

            # ── 2. get_schema ──
            r = await session.call_tool("get_schema", {"db": "md"})
            print("\n[get_schema(md)] 先頭120字:")
            print(" ", r.content[0].text[:120].replace("\n", " "))

            # ── 3. run_query 正常系（ハンマー差分・NULL除外つき）──
            sql = (
                "SELECT AVG(CASE WHEN color_hammer='red' "
                "THEN score_red-score_yellow ELSE score_yellow-score_red END) AS hammer_adv "
                "FROM ends WHERE score_red IS NOT NULL AND score_yellow IS NOT NULL"
            )
            r = await session.call_tool("run_query", {"sql": sql, "db": "md"})
            payload = json.loads(r.content[0].text)
            print("\n[run_query 集計] hammer_adv =", payload["rows"][0][0])

            # ── 4. run_query 行数上限（truncated）──
            r = await session.call_tool("run_query", {"sql": "SELECT id FROM ends", "db": "md"})
            payload = json.loads(r.content[0].text)
            print(
                "[run_query 全件] row_count =",
                payload["row_count"],
                "/ truncated =",
                payload["truncated"],
            )

            # ── 5. run_query 異常系（書き込みは拒否されるべき）──
            r = await session.call_tool("run_query", {"sql": "DELETE FROM ends", "db": "md"})
            print("[run_query DELETE] isError =", r.isError)
            print("  →", r.content[0].text[:70])

            # ── 6. リソース読み込み ──
            res = await session.read_resource("rb2db://sql-notes")
            print("\n[resource sql-notes] 先頭60字:")
            print(" ", res.contents[0].text[:60].replace("\n", " "))

    print("\nスモークテスト完了。上の各項目が期待通りか目視で確認すること。")


def main() -> None:
    """エントリポイント。非同期のチェックを実行する。"""
    asyncio.run(run_checks())


if __name__ == "__main__":
    main()
