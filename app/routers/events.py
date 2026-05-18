"""events ルーター。大会の一覧・単一取得・配下の試合一覧を提供する。"""

from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException
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


def create_router(get_db: Callable[[], Generator[Session, None, None]]) -> APIRouter:
    """events ルーターを生成して返すファクトリ関数。

    同じルーター定義を md / four 両 DB で使い回すために、
    DB セッション取得関数（get_db）を引数として受け取る。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）

    Returns:
        APIRouter: 設定済みの events ルーター
    """

    # APIRouter: エンドポイントをグループ化するオブジェクト
    # main.py で include_router するときに prefix="/v1/md" などが付与される
    router = APIRouter()

    @router.get("/events", response_model=ListResponse[EventResponse])
    def list_events(
        # --- ページネーション ---
        limit: int = 50,    # 取得件数の上限（デフォルト50）
        offset: int = 0,    # 取得開始位置（デフォルト0）
        # --- ソート ---
        # Enum 型にすることで定義外の値は FastAPI が自動で 422 エラーを返す
        sort: EventSortField = EventSortField.id,
        order: OrderDirection = OrderDirection.asc,
        # --- DB セッション ---
        # Depends(get_db): リクエストごとに DB セッションを自動で用意・クローズ
        db: Session = Depends(get_db),
    ) -> ListResponse[EventResponse]:
        """大会一覧を取得する。

        Args:
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[EventResponse]: 総件数・ページネーション情報・大会リスト
        """
        # ベースクエリ: SELECT * FROM events
        query = db.query(Event)

        # ソート方向の関数を選択（asc=昇順 / desc=降順）
        order_func = asc if order == OrderDirection.asc else desc

        # sort.value で Enum の文字列値（例: "year"）を取得し、
        # getattr で Event クラスの対応するカラムオブジェクトを取得
        query = query.order_by(order_func(getattr(Event, sort.value)))

        # total: フィルタ後・ページネーション前の総件数
        total = query.count()

        # offset で開始位置をスキップし、limit で件数を制限
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/events/{event_id}", response_model=EventResponse)
    def get_event(
        event_id: int,
        db: Session = Depends(get_db),
    ) -> EventResponse:
        """大会を1件取得する。

        Args:
            event_id: 取得する大会の ID（URL パスから自動取得）
            db: DB セッション（依存性注入）

        Returns:
            EventResponse: 大会情報

        Raises:
            HTTPException: 指定 ID の大会が存在しない場合（404）
        """
        # filter: WHERE events.id = event_id
        # first: 最初の1件を取得（存在しない場合は None）
        event = db.query(Event).filter(Event.id == event_id).first()

        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        return event

    @router.get("/events/{event_id}/games", response_model=ListResponse[GameResponse])
    def list_event_games(
        event_id: int,
        limit: int = 50,
        offset: int = 0,
        sort: GameSortField = GameSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[GameResponse]:
        """大会に属する試合一覧を取得する。

        Args:
            event_id: 大会 ID（URL パスから自動取得）
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[GameResponse]: 総件数・ページネーション情報・試合リスト

        Raises:
            HTTPException: 指定 ID の大会が存在しない場合（404）
        """
        # 大会の存在確認（存在しない event_id には 404 を返す）
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
