"""events ルーター。大会の一覧・単一取得・配下の試合一覧を提供する。"""

from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import Event, Game
from app.schemas import (
    EventResponse,
    EventSortField,
    GameResponse,
    GameSortField,
    ListResponse,
    OrderDirection,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """events ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの events ルーター
    """
    router = APIRouter()

    @router.get("/events", response_model=ListResponse[EventResponse])
    @limiter.limit(rate_limit)
    # request は slowapi がIPアドレスを取得するために必要（クエリパラメータにはならない）
    def list_events(
        request: Request,  # noqa: ARG001
        # Query() でデフォルト値に加えて範囲制限を設定する
        # ge=1: 1以上（ge = greater than or equal）
        # le=1000: 1000以下（le = less than or equal）
        # ge=0: 0以上
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort: EventSortField = EventSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[EventResponse]:
        """大会一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜1000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[EventResponse]: 総件数・ページネーション情報・大会リスト
        """
        query = db.query(Event)
        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Event, sort.value)))
        total = query.count()
        records = query.offset(offset).limit(limit).all()
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/events/{event_id}", response_model=EventResponse)
    @limiter.limit(rate_limit)
    def get_event(
        request: Request,  # noqa: ARG001
        event_id: int,
        db: Session = Depends(get_db),
    ) -> EventResponse:
        """大会を1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            event_id: 取得する大会の ID（URL パスから自動取得）
            db: DB セッション（依存性注入）

        Returns:
            EventResponse: 大会情報

        Raises:
            HTTPException: 指定 ID の大会が存在しない場合（404）
        """
        event = db.query(Event).filter(Event.id == event_id).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        return event

    @router.get("/events/{event_id}/games", response_model=ListResponse[GameResponse])
    @limiter.limit(rate_limit)
    def list_event_games(
        request: Request,  # noqa: ARG001
        event_id: int,
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort: GameSortField = GameSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[GameResponse]:
        """大会に属する試合一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            event_id: 大会 ID（URL パスから自動取得）
            limit: 取得件数の上限（1〜1000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[GameResponse]: 総件数・ページネーション情報・試合リスト

        Raises:
            HTTPException: 指定 ID の大会が存在しない場合（404）
        """
        event = db.query(Event).filter(Event.id == event_id).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        order_func = asc if order == OrderDirection.asc else desc
        query = (
            db.query(Game)
            .filter(Game.event_id == event_id)
            .order_by(order_func(getattr(Game, sort.value)))
        )
        total = query.count()
        records = query.offset(offset).limit(limit).all()
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
