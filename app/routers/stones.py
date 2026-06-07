"""stones ルーター。ストーン座標の一覧・単一取得を提供する。"""

from collections.abc import Callable, Generator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import Stone
from app.schemas import (
    ListResponse,
    OrderDirection,
    StoneColor,
    StoneResponse,
    StoneSortField,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """stones ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの stones ルーター
    """
    router = APIRouter()

    @router.get("/stones", response_model=ListResponse[StoneResponse])
    @limiter.limit(rate_limit)
    def list_stones(
        request: Request,  # noqa: ARG001
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort: StoneSortField = StoneSortField.id,
        order: OrderDirection = OrderDirection.asc,
        shot_id: int | None = None,
        color: StoneColor | None = None,
        inhouse: int | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[StoneResponse]:
        """ストーン座標一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜1000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            shot_id: 投球IDで絞り込み（省略可）
            color: ストーン色で絞り込み（"red" / "yellow"、省略可）
            inhouse: ハウス内フラグで絞り込み（0 / 1、省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[StoneResponse]: 総件数・ページネーション情報・ストーンリスト
        """
        query = db.query(Stone)

        if shot_id is not None:
            query = query.filter(Stone.shot_id == shot_id)
        if color is not None:
            query = query.filter(Stone.color == color)
        if inhouse is not None:
            query = query.filter(Stone.inhouse == inhouse)

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Stone, sort.value)))
        total = query.count()
        records = cast(list[StoneResponse], query.offset(offset).limit(limit).all())
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/stones/{stone_id}", response_model=StoneResponse)
    @limiter.limit(rate_limit)
    def get_stone(
        request: Request,  # noqa: ARG001
        stone_id: int,
        db: Session = Depends(get_db),
    ) -> StoneResponse:
        """ストーン座標を1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            stone_id: 取得するストーンの ID
            db: DB セッション（依存性注入）

        Returns:
            StoneResponse: ストーン座標情報

        Raises:
            HTTPException: 指定 ID のストーンが存在しない場合（404）
        """
        stone = db.query(Stone).filter(Stone.id == stone_id).first()
        if stone is None:
            raise HTTPException(status_code=404, detail="Stone not found")
        return stone

    return router
