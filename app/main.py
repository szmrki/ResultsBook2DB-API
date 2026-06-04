"""
FastAPI アプリケーションのエントリーポイント。

ここでやること:
  1. ログシステムの初期化
  2. FastAPI インスタンスの作成
  3. slowapi によるレートリミット設定（DoS 対策）
  4. カスタムエラーハンドラの登録（レスポンス形式を統一）
  5. ロギングミドルウェアの登録（リクエスト/レスポンストレース）
  6. md / normal 両 DB 用ルーターの登録
  7. ヘルスチェックエンドポイントの定義
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import Response

load_dotenv()

from app.database import get_four_db, get_md_db  # noqa: E402
from app.logging import get_logger, setup_logging  # noqa: E402
from app.routers import ends, events, games, lsds, shots, stones  # noqa: E402
from app.schemas import EndFourResponse, EndMdResponse  # noqa: E402

# ─── ログ設定初期化 ───────────────────────────────────────────────────────────
setup_logging()
logger = get_logger(__name__)


# ─── ライフサイクルイベント ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """アプリケーションのライフサイクル管理。

    Args:
        _app: FastAPI インスタンス（引数として必須だが未使用）

    Yields:
        None: 起動完了から終了開始までの間
    """
    logger.info("Application started successfully")
    yield
    logger.info("Application is shutting down")


# ─── レートリミット設定 ───────────────────────────────────────────────────────
# get_remote_address: クライアントの IP アドレスをキーにしてリクエスト数を制限
limiter = Limiter(key_func=get_remote_address)

# 全エンドポイント共通のレートリミット上限
# 変更する場合はここだけ修正すれば全体に反映される
# 特定のエンドポイントだけ制限を変えたい場合は、そのルーター内でハードコードする
RATE_LIMIT = "100/minute"

# ─── FastAPI アプリ初期化 ──────────────────────────────────────────────────────
app = FastAPI(
    title="ResultsBook2DB-API",
    version="1.0.0",
    description="カーリング実試合データ API",
    lifespan=lifespan,
)

# slowapi をアプリに紐づける
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# ─── カスタムエラーハンドラ ────────────────────────────────────────────────────
# FastAPI のデフォルトは {"detail": "..."} のみ。
# api_design.md の仕様に合わせて status_code もボディに含める。

@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """HTTP エラー（404 など）のレスポンス形式を統一する。

    Args:
        _request: FastAPI のリクエストオブジェクト（ハンドラの引数として必須だが未使用）
        exc: 発生した HTTPException

    Returns:
        JSONResponse: {"detail": "...", "status_code": N} 形式のレスポンス
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """バリデーションエラー（422）のレスポンス形式を統一する。

    Enum 型のクエリパラメータに定義外の値が渡された場合などに発生する。

    Args:
        _request: FastAPI のリクエストオブジェクト（ハンドラの引数として必須だが未使用）
        exc: 発生した RequestValidationError

    Returns:
        JSONResponse: {"detail": [...], "status_code": 422} 形式のレスポンス
    """
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "status_code": 422},
    )


# ─── ミドルウェア ──────────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """リクエスト・レスポンスをログに記録するミドルウェア。

    リクエスト受信時刻とレスポンス送信時刻から処理時間を計測し、
    ステータスコードと共にログ出力する。

    Args:
        request: FastAPI のリクエストオブジェクト
        call_next: 次のミドルウェアまたはエンドポイントを実行するコルーチン

    Returns:
        レスポンスオブジェクト
    """
    # リクエスト受信時刻（ミリ秒単位）
    start_time = time.time()

    # 次の処理を実行（予期しない例外はスタックトレース付きでログに残して再 raise）
    try:
        response = await call_next(request)
    except Exception as e:
        logger.exception("Unhandled exception", exc_info=e)
        raise

    # レスポンス送信時刻から処理時間を計算
    duration_ms = (time.time() - start_time) * 1000

    # ステータスコード 4xx / 5xx は WARNING、それ以外は INFO
    # duration_ms と status_code を extra に渡すことで JSON モード時に構造化フィールドとして出力される
    client_ip = request.client.host if request.client else "unknown"
    log_func = logger.warning if response.status_code >= 400 else logger.info
    log_func(
        f"{client_ip} {request.method} {request.url.path} -> {response.status_code}",
        extra={
            "client_ip": client_ip,
            "duration_ms": round(duration_ms, 2),
            "status_code": response.status_code,
        },
    )

    return response


# ─── ルーター登録 ──────────────────────────────────────────────────────────────
# create_router(get_db) はルーターファクトリ関数（routers/ 各ファイル参照）。
# 同じルーター定義を md / normal 両方に使い回す。
# ends と games は EndResponse（レスポンスモデル）も引数に取る（md/normal で異なるため）。

# --- four DB ルーター ---
app.include_router(
    events.create_router(get_four_db, limiter, RATE_LIMIT),
    prefix="/v1/four",
    tags=["four / events"],
)
app.include_router(
    games.create_router(get_four_db, EndFourResponse, limiter, RATE_LIMIT),
    prefix="/v1/four",
    tags=["four / games"],
)
app.include_router(
    ends.create_router(get_four_db, EndFourResponse, limiter, RATE_LIMIT),
    prefix="/v1/four",
    tags=["four / ends"],
)
app.include_router(
    shots.create_router(get_four_db, limiter, RATE_LIMIT),
    prefix="/v1/four",
    tags=["four / shots"],
)
app.include_router(
    stones.create_router(get_four_db, limiter, RATE_LIMIT),
    prefix="/v1/four",
    tags=["four / stones"],
)
app.include_router(
    lsds.create_router(get_four_db, limiter, RATE_LIMIT),
    prefix="/v1/four",
    tags=["four / lsds"],
)

# --- md DB ルーター ---
app.include_router(
    events.create_router(get_md_db, limiter, RATE_LIMIT),
    prefix="/v1/md",
    tags=["md / events"],
)
app.include_router(
    games.create_router(get_md_db, EndMdResponse, limiter, RATE_LIMIT),
    prefix="/v1/md",
    tags=["md / games"],
)
app.include_router(
    ends.create_router(get_md_db, EndMdResponse, limiter, RATE_LIMIT),
    prefix="/v1/md",
    tags=["md / ends"],
)
app.include_router(
    shots.create_router(get_md_db, limiter, RATE_LIMIT),
    prefix="/v1/md",
    tags=["md / shots"],
)
app.include_router(
    stones.create_router(get_md_db, limiter, RATE_LIMIT),
    prefix="/v1/md",
    tags=["md / stones"],
)
app.include_router(
    lsds.create_router(get_md_db, limiter, RATE_LIMIT),
    prefix="/v1/md",
    tags=["md / lsds"],
)


# ─── ヘルスチェック ────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def health_check() -> dict[str, str]:
    """サーバーの起動確認用エンドポイント。

    Returns:
        dict: {"status": "ok"}
    """
    return {"status": "ok"}
