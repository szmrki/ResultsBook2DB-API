"""games ルーター。試合の一覧・単一取得・配下のエンド一覧・LSD一覧を提供する。"""

from collections.abc import Callable, Generator
from typing import Union, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import End, Game, Lsd
from app.schemas import (
    EndFourResponse,
    EndMdResponse,
    EndSortField,
    GameResponse,
    GameSortField,
    ListResponse,
    LsdResponse,
    LsdSortField,
    OrderDirection,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    end_response_model: type[Union[EndMdResponse, EndFourResponse]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """games ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        end_response_model: ends のレスポンスモデル（md / four で異なる）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの games ルーター
    """
    router = APIRouter()

    @router.get("/games", response_model=ListResponse[GameResponse])
    @limiter.limit(rate_limit)
    def list_games(
        request: Request,  # noqa: ARG001
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort: GameSortField = GameSortField.id,
        order: OrderDirection = OrderDirection.asc,
        event_id: int | None = None,
        team: str | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[GameResponse]:
        """試合一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜1000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            event_id: 大会IDで絞り込み（省略可）
            team: チーム名の部分一致で絞り込み（省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[GameResponse]: 総件数・ページネーション情報・試合リスト
        """
        query = db.query(Game)

        if event_id is not None:
            query = query.filter(Game.event_id == event_id)
        if team is not None:
            query = query.filter(
                (Game.team_red.ilike(f"%{team}%")) | (Game.team_yellow.ilike(f"%{team}%"))
            )

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Game, sort.value)))
        total = query.count()
        records = cast(list[GameResponse], query.offset(offset).limit(limit).all())
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/games/{game_id}", response_model=GameResponse)
    @limiter.limit(rate_limit)
    def get_game(
        request: Request,  # noqa: ARG001
        game_id: int,
        db: Session = Depends(get_db),
    ) -> GameResponse:
        """試合を1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            game_id: 取得する試合の ID
            db: DB セッション（依存性注入）

        Returns:
            GameResponse: 試合情報

        Raises:
            HTTPException: 指定 ID の試合が存在しない場合（404）
        """
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")
        return game

    @router.get(
        "/games/{game_id}/ends",
        response_model=ListResponse[end_response_model],  # type: ignore[valid-type]
    )
    @limiter.limit(rate_limit)
    def list_game_ends(
        request: Request,  # noqa: ARG001
        game_id: int,
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort: EndSortField = EndSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse:
        """試合に属するエンド一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            game_id: 試合 ID
            limit: 取得件数の上限（1〜1000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse: 総件数・ページネーション情報・エンドリスト

        Raises:
            HTTPException: 指定 ID の試合が存在しない場合（404）
        """
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")

        order_func = asc if order == OrderDirection.asc else desc
        query = (
            db.query(End)
            .filter(End.game_id == game_id)
            .order_by(order_func(getattr(End, sort.value)))
        )
        total = query.count()
        records = cast(
            list[EndMdResponse | EndFourResponse], query.offset(offset).limit(limit).all()
        )
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/games/{game_id}/lsds", response_model=ListResponse[LsdResponse])
    @limiter.limit(rate_limit)
    def list_game_lsds(
        request: Request,  # noqa: ARG001
        game_id: int,
        limit: int = Query(default=50, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort: LsdSortField = LsdSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[LsdResponse]:
        """試合に属する LSD 一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            game_id: 試合 ID
            limit: 取得件数の上限（1〜1000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[LsdResponse]: 総件数・ページネーション情報・LSD リスト

        Raises:
            HTTPException: 指定 ID の試合が存在しない場合（404）
        """
        game = db.query(Game).filter(Game.id == game_id).first()
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")

        order_func = asc if order == OrderDirection.asc else desc
        query = (
            db.query(Lsd)
            .filter(Lsd.game_id == game_id)
            .order_by(order_func(getattr(Lsd, sort.value)))
        )
        total = query.count()
        records = cast(list[LsdResponse], query.offset(offset).limit(limit).all())
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
