"""notes ルーター。DB を扱ううえでの前提知識（Markdown）を配信する。

このルーターの存在理由:
    rb2db は「知らないと必ず間違える」落とし穴をいくつも持っている
    （ends の NULL がコンシード由来である、stones.shot_order に負値が混ざる、等）。
    MCP サーバー側はこの知識を `rb2db://schema` などのリソースとして配信しており、
    AI ツールから接続した利用者は自動的にこれを読める。

    一方 REST API の利用者にはその経路がなく、同じ DB を触っているのに
    落とし穴を回避できない、という非対称が生まれていた。このルーターは
    **MCP と同じ Markdown の実体（app/mcp/knowledge/*.md）**をそのまま配信して
    その差を埋める。知識の実体はあくまで1箇所なので、更新の二重管理は起きない。
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from slowapi import Limiter

from app.mcp import knowledge
from app.schemas import NoteDoc, NoteResponse

# 配信対象の Markdown。
# キー   : URL に現れる文書名（NoteDoc の値と一致させる）
# 値     : (実ファイル名, 一覧に出す説明文)
# ここに載っているものだけを配信する。任意のファイル名を URL から受け取って
# そのまま開く作りにすると、パストラバーサル（../ で別ファイルを読む攻撃）を
# 許してしまうため、ホワイトリスト方式にしている。
_DOCS: dict[str, tuple[str, str]] = {
    "schema": ("schema.md", "テーブル定義・カラムの意味・リレーション・md/four 差分"),
    "sql-notes": ("sql_notes.md", "データ上の注意点（NULL の意味・異常値・座標系など）"),
    "metrics": ("metrics.md", "定義済みメトリクスの定義集（ハンマー差分・スチール率など）"),
}


def create_router(limiter: Limiter, rate_limit: str) -> APIRouter:
    """notes ルーターを生成して返すファクトリ関数。

    他のルーターと違い DB セッションを取らない（静的な同梱ドキュメントを返すだけで、
    DB にアクセスしないため）。md / four のどちらにも属さない共通の情報なので、
    main.py では `/v1/four` `/v1/md` ではなく `/v1` 直下に登録する。

    Args:
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）

    Returns:
        APIRouter: 設定済みの notes ルーター
    """
    router = APIRouter()

    @router.get(
        "/notes",
        response_model=list[NoteResponse],
        summary="前提知識ドキュメントの一覧",
        # description は OpenAPI 経由で外部に公開されるため、文書の中身には触れず
        # 「一覧が取れる」ことだけを書く。実際の内容は API 本体（研究室内限定公開）
        # にアクセスできる利用者だけが取得できる。
        description=(
            "この API のデータを正しく扱うための前提知識ドキュメントの一覧を返す。\n\n"
            "本文は `GET /v1/notes/{doc}` で取得できる。\n\n"
            "**分析目的でこの API を使う場合は、集計を書く前に目を通すことを推奨する。**"
        ),
    )
    @limiter.limit(rate_limit)
    def list_notes(request: Request) -> list[NoteResponse]:  # noqa: ARG001
        """配信している前提知識ドキュメントの一覧を返す。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）

        Returns:
            list[NoteResponse]: 文書名・説明・取得URLのリスト
        """
        return [
            NoteResponse(doc=doc, description=description, url=f"/v1/notes/{doc}")
            for doc, (_filename, description) in _DOCS.items()
        ]

    @router.get(
        "/notes/{doc}",
        response_class=PlainTextResponse,
        summary="前提知識ドキュメントの本文",
        description=(
            "前提知識ドキュメントの本文を Markdown（`text/markdown`）で返す。\n\n"
            "指定できる文書名は `GET /v1/notes` の一覧を参照。"
        ),
        responses={200: {"content": {"text/markdown": {}}}},
    )
    @limiter.limit(rate_limit)
    def get_note(request: Request, doc: NoteDoc) -> PlainTextResponse:  # noqa: ARG001
        """前提知識ドキュメントの本文を Markdown で返す。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            doc: 取得する文書名（"schema" / "sql-notes" / "metrics"）

        Returns:
            PlainTextResponse: Markdown 本文（media_type は text/markdown）

        Raises:
            HTTPException: 同梱ドキュメントの読み込みに失敗した場合（500）
        """
        # doc は Enum なので、ここに来る時点で _DOCS のキーであることは保証されている
        # （定義外の値は FastAPI が 422 で弾く）。
        filename, _description = _DOCS[doc.value]
        try:
            content = knowledge.load(filename)
        except (FileNotFoundError, OSError) as e:
            # パッケージに同梱されているはずのファイルが読めない = デプロイの不整合。
            # 利用者側では対処できないので 500 で返す。
            raise HTTPException(
                status_code=500, detail=f"Document '{doc.value}' could not be loaded"
            ) from e
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")

    return router
