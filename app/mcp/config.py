"""MCP サーバーの設定値。

環境変数から読み取る接続情報とガードレールの具体値を1か所に集約する。
設計書（memo/mcp_server_design.md §4.1 / §8）で確定した値をここで定義する。
"""

import os

# ── read-only ロール用の接続URL ────────────────────────────────────
# 既存 REST API が使う書き込み可能な DATABASE_URL_* とは別に、
# read-only 専用ロールで接続するURLを用意する。
# read-only ロールは docker/setup_readonly_role.sql で作成する。
# md   : ミックスダブルス（2人制）のDB
# four : 4人制（Men / Women / Junior）のDB
DATABASE_URL_MD_RO = os.environ["DATABASE_URL_MD_RO"]
DATABASE_URL_FOUR_RO = os.environ["DATABASE_URL_FOUR_RO"]

# ── ガードレールの具体値 ───────────────────────────────────────────
# 行数上限: run_query が返す最大行数。これを超えた分は切り落とし、
# 結果JSONの truncated=true でAIに「絞られた」ことを伝える。
MAX_ROWS = 10_000

# ── 大量データ取得の誘導先（REST API）────────────────────────────
# run_query は結果が AI のコンテキストを経由するため、大量の生データ取得には向かない。
# その場合は「スクリプトから REST API を呼んでファイルに保存する」よう AI を誘導する。
# instructions と truncated 時のヒントに、この URL を差し込んで案内する。
#
# 本番の URL はコードに書かず、サーバーの .env（Git 管理外）だけに置く。
# リポジトリが public なので、既定値として書くと本番のホスト名が公開されてしまうため。
# 未設定（空文字）のときは、AI に「URL はユーザーに確認する」よう案内する。
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "").rstrip("/")

# URL が未設定のときに、案内文の中で URL の代わりに置く目印。
API_URL_PLACEHOLDER = "<API_URL>"


def api_url_label(api_url: str) -> str:
    """案内文に差し込む API の URL を返す。未設定なら目印の文字列を返す。

    Args:
        api_url: 設定された API の URL（未設定なら空文字）。

    Returns:
        api_url が空でなければそのまま、空なら API_URL_PLACEHOLDER。
    """
    return api_url or API_URL_PLACEHOLDER

# クエリのタイムアウト（ミリ秒）。PostgreSQL の statement_timeout に渡す。
# 長時間クエリを DB 側で打ち切る主たる防御線の一つ。
STATEMENT_TIMEOUT_MS = 30_000

# ── サーバーの待ち受け設定 ─────────────────────────────────────────
# 研究室サーバーの localhost のみで待ち受け、各メンバーは SSH トンネル経由で接続する。
# 0.0.0.0 にするのは docker コンテナ内から公開する場合（compose 側でホスト側を
# 127.0.0.1 に限定する）。ここではデフォルトを 0.0.0.0 とし、環境変数で上書き可能にする。
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8100"))
