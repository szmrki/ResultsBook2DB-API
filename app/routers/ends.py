"""ends ルーター。エンドの一覧・単一取得・配下のショット一覧を提供する。"""

from collections.abc import Callable, Generator
from typing import Union

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import End, Shot
from app.schemas import (
    EndMdResponse,
    EndFourResponse,
    EndSortField,
    ListResponse,
    OrderDirection,
    ShotResponse,
    ShotSortField,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    end_response_model: type[Union[EndMdResponse, EndFourResponse]],
) -> APIRouter:
    """ends ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        end_response_model: ends のレスポンスモデル（md / four で異なる）

    Returns:
        APIRouter: 設定済みの ends ルーター
    """
    router = APIRouter()

    @router.get("/ends", response_model=ListResponse[end_response_model])
    def list_ends(
        limit: int = 50,
        offset: int = 0,
        sort: EndSortField = EndSortField.id,
        order: OrderDirection = OrderDirection.asc,
        game_id: int | None = None,
        color_hammer: str | None = None,
        is_power_play: int | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse:
        """エンド一覧を取得する。

        Args:
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            game_id: 試合IDで絞り込み（省略可）
            color_hammer: ハンマー色で絞り込み（"red" / "yellow"、省略可）
            is_power_play: パワープレイフラグで絞り込み（0 / 1、md のみ有効、省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse: 総件数・ページネーション情報・エンドリスト
        """
        query = db.query(End)

        if game_id is not None:
            query = query.filter(End.game_id == game_id)
        if color_hammer is not None:
            query = query.filter(End.color_hammer == color_hammer)
        if is_power_play is not None:
            query = query.filter(End.is_power_play == is_power_play)

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(End, sort.value)))

        total = query.count()
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/ends/{end_id}", response_model=end_response_model)
    def get_end(
        end_id: int,
        db: Session = Depends(get_db),
    ) -> End:
        """エンドを1件取得する。

        Args:
            end_id: 取得するエンドの ID
            db: DB セッション（依存性注入）

        Returns:
            End: エンド情報

        Raises:
            HTTPException: 指定 ID のエンドが存在しない場合（404）
        """
        end = db.query(End).filter(End.id == end_id).first()
        if end is None:
            raise HTTPException(status_code=404, detail="End not found")
        return end

    @router.get("/ends/{end_id}/shots", response_model=ListResponse[ShotResponse])
    def list_end_shots(
        end_id: int,
        limit: int = 50,
        offset: int = 0,
        sort: ShotSortField = ShotSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[ShotResponse]:
        """エンドに属するショット一覧を取得する。

        Args:
            end_id: エンド ID
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[ShotResponse]: 総件数・ページネーション情報・ショットリスト

        Raises:
            HTTPException: 指定 ID のエンドが存在しない場合（404）
        """
        end = db.query(End).filter(End.id == end_id).first()
        if end is None:
            raise HTTPException(status_code=404, detail="End not found")

        order_func = asc if order == OrderDirection.asc else desc
        query = (
            db.query(Shot)
            .filter(Shot.end_id == end_id)
            .order_by(order_func(getattr(Shot, sort.value)))
        )

        total = query.count()
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
