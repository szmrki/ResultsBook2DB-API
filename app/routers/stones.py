"""stones ルーター。ストーン座標の一覧・単一取得を提供する。"""

from collections.abc import Callable, Generator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import End, Game, Shot, Stone
from app.pagination import limit_query, offset_query
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
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: StoneSortField = StoneSortField.id,
        order: OrderDirection = OrderDirection.asc,
        event_id: int | None = None,
        game_id: int | None = None,
        end_id: int | None = None,
        shot_id: int | None = None,
        color: StoneColor | None = None,
        inhouse: int | None = None,
        shot_order: int | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[StoneResponse]:
        """ストーン座標一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            event_id: 大会IDで絞り込み（省略可。stones→shots→ends→games を辿って絞る）
            game_id: 試合IDで絞り込み（省略可。stones→shots→ends を辿って絞る）
            end_id: エンドIDで絞り込み（省略可。stones→shots を辿って絞る）
            shot_id: 投球IDで絞り込み（省略可）
            color: ストーン色で絞り込み（"red" / "yellow"、省略可）
            inhouse: ハウス内フラグで絞り込み（0 / 1、省略可）
            shot_order: 投球順で絞り込み（省略可。four DB のみ、md DB では NULL）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[StoneResponse]: 総件数・ページネーション情報・ストーンリスト
        """
        query = db.query(Stone)

        # event_id / game_id / end_id はいずれも Shot を経由するため、
        # どれか1つでも指定されたら Shot を1回だけ JOIN する（重複 JOIN を防ぐ）。
        if event_id is not None or game_id is not None or end_id is not None:
            query = query.join(Shot, Stone.shot_id == Shot.id)
        # event_id / game_id はさらに End を経由する。
        if event_id is not None or game_id is not None:
            query = query.join(End, Shot.end_id == End.id)
        # event_id は最上位に近い Game まで辿る。
        if event_id is not None:
            query = query.join(Game, End.game_id == Game.id).filter(
                Game.event_id == event_id
            )
        if game_id is not None:
            query = query.filter(End.game_id == game_id)
        if end_id is not None:
            query = query.filter(Shot.end_id == end_id)
        if shot_id is not None:
            query = query.filter(Stone.shot_id == shot_id)
        if color is not None:
            query = query.filter(Stone.color == color)
        if inhouse is not None:
            query = query.filter(Stone.inhouse == inhouse)
        if shot_order is not None:
            query = query.filter(Stone.shot_order == shot_order)

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
