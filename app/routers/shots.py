"""shots ルーター。ショットの一覧・単一取得・配下のストーン座標一覧を提供する。"""

from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import Shot, Stone
from app.schemas import (
    ListResponse,
    OrderDirection,
    ShotResponse,
    ShotSortField,
    StoneResponse,
    StoneSortField,
)


def create_router(get_db: Callable[[], Generator[Session, None, None]]) -> APIRouter:
    """shots ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）

    Returns:
        APIRouter: 設定済みの shots ルーター
    """
    router = APIRouter()

    @router.get("/shots", response_model=ListResponse[ShotResponse])
    def list_shots(
        limit: int = 50,
        offset: int = 0,
        sort: ShotSortField = ShotSortField.id,
        order: OrderDirection = OrderDirection.asc,
        end_id: int | None = None,
        player_name: str | None = None,
        type: str | None = None,
        color: str | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[ShotResponse]:
        """ショット一覧を取得する。

        Args:
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            end_id: エンドIDで絞り込み（省略可）
            player_name: 選手名の部分一致で絞り込み（省略可）
            type: ショットタイプで絞り込み（省略可）
            color: ストーン色で絞り込み（"red" / "yellow"、省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[ShotResponse]: 総件数・ページネーション情報・ショットリスト
        """
        query = db.query(Shot)

        if end_id is not None:
            query = query.filter(Shot.end_id == end_id)
        if player_name is not None:
            query = query.filter(Shot.player_name.ilike(f"%{player_name}%"))
        if type is not None:
            query = query.filter(Shot.type == type)
        if color is not None:
            query = query.filter(Shot.color == color)

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Shot, sort.value)))

        total = query.count()
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/shots/{shot_id}", response_model=ShotResponse)
    def get_shot(
        shot_id: int,
        db: Session = Depends(get_db),
    ) -> ShotResponse:
        """ショットを1件取得する。

        Args:
            shot_id: 取得するショットの ID
            db: DB セッション（依存性注入）

        Returns:
            ShotResponse: ショット情報

        Raises:
            HTTPException: 指定 ID のショットが存在しない場合（404）
        """
        shot = db.query(Shot).filter(Shot.id == shot_id).first()
        if shot is None:
            raise HTTPException(status_code=404, detail="Shot not found")
        return shot

    @router.get("/shots/{shot_id}/stones", response_model=ListResponse[StoneResponse])
    def list_shot_stones(
        shot_id: int,
        limit: int = 50,
        offset: int = 0,
        sort: StoneSortField = StoneSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[StoneResponse]:
        """ショット後のストーン座標一覧を取得する。

        Args:
            shot_id: ショット ID
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[StoneResponse]: 総件数・ページネーション情報・ストーンリスト

        Raises:
            HTTPException: 指定 ID のショットが存在しない場合（404）
        """
        shot = db.query(Shot).filter(Shot.id == shot_id).first()
        if shot is None:
            raise HTTPException(status_code=404, detail="Shot not found")

        order_func = asc if order == OrderDirection.asc else desc
        query = (
            db.query(Stone)
            .filter(Stone.shot_id == shot_id)
            .order_by(order_func(getattr(Stone, sort.value)))
        )

        total = query.count()
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
