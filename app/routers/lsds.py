"""lsds ルーター。LSD の一覧・単一取得を提供する。"""

from collections.abc import Callable, Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import Lsd
from app.schemas import (
    ListResponse,
    LsdResponse,
    LsdSortField,
    OrderDirection,
)


def create_router(get_db: Callable[[], Generator[Session, None, None]]) -> APIRouter:
    """lsds ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）

    Returns:
        APIRouter: 設定済みの lsds ルーター
    """
    router = APIRouter()

    @router.get("/lsds", response_model=ListResponse[LsdResponse])
    def list_lsds(
        limit: int = 50,
        offset: int = 0,
        sort: LsdSortField = LsdSortField.id,
        order: OrderDirection = OrderDirection.asc,
        game_id: int | None = None,
        team: str | None = None,
        player_name: str | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[LsdResponse]:
        """LSD 一覧を取得する。

        Args:
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            game_id: 試合IDで絞り込み（省略可）
            team: チーム名の部分一致で絞り込み（省略可）
            player_name: 選手名の部分一致で絞り込み（省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[LsdResponse]: 総件数・ページネーション情報・LSD リスト
        """
        query = db.query(Lsd)

        if game_id is not None:
            query = query.filter(Lsd.game_id == game_id)
        if team is not None:
            query = query.filter(Lsd.team.ilike(f"%{team}%"))
        if player_name is not None:
            query = query.filter(Lsd.player_name.ilike(f"%{player_name}%"))

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Lsd, sort.value)))

        total = query.count()
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/lsds/{lsd_id}", response_model=LsdResponse)
    def get_lsd(
        lsd_id: int,
        db: Session = Depends(get_db),
    ) -> LsdResponse:
        """LSD を1件取得する。

        Args:
            lsd_id: 取得する LSD の ID
            db: DB セッション（依存性注入）

        Returns:
            LsdResponse: LSD 情報

        Raises:
            HTTPException: 指定 ID の LSD が存在しない場合（404）
        """
        lsd = db.query(Lsd).filter(Lsd.id == lsd_id).first()
        if lsd is None:
            raise HTTPException(status_code=404, detail="Lsd not found")
        return lsd

    return router
