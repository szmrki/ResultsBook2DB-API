"""standings ルーター。大会順位の一覧・単一取得を提供する。"""

from collections.abc import Callable, Generator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import Standing
from app.pagination import limit_query, offset_query
from app.schemas import (
    ListResponse,
    OrderDirection,
    StandingResponse,
    StandingSortField,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """standings ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの standings ルーター
    """
    router = APIRouter()

    @router.get("/standings", response_model=ListResponse[StandingResponse])
    @limiter.limit(rate_limit)
    def list_standings(
        request: Request,  # noqa: ARG001
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: StandingSortField = StandingSortField.id,
        order: OrderDirection = OrderDirection.asc,
        event_id: int | None = None,
        team: str | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[StandingResponse]:
        """順位一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            event_id: 大会IDで絞り込み（省略可）
            team: チーム名の部分一致で絞り込み（省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[StandingResponse]: 総件数・ページネーション情報・順位リスト
        """
        query = db.query(Standing)

        if event_id is not None:
            query = query.filter(Standing.event_id == event_id)
        if team is not None:
            query = query.filter(Standing.team.ilike(f"%{team}%"))

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Standing, sort.value)))
        total = query.count()
        records = cast(
            list[StandingResponse], query.offset(offset).limit(limit).all()
        )
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/standings/{standing_id}", response_model=StandingResponse)
    @limiter.limit(rate_limit)
    def get_standing(
        request: Request,  # noqa: ARG001
        standing_id: int,
        db: Session = Depends(get_db),
    ) -> Standing:
        """順位を1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            standing_id: 取得する順位レコードの ID
            db: DB セッション（依存性注入）

        Returns:
            Standing: 順位情報

        Raises:
            HTTPException: 指定 ID の順位レコードが存在しない場合（404）
        """
        standing = db.query(Standing).filter(Standing.id == standing_id).first()
        if standing is None:
            raise HTTPException(status_code=404, detail="Standing not found")
        return standing

    return router
