"""games ルーター。試合の一覧・単一取得・配下のエンド一覧・LSD一覧を提供する。"""

from collections.abc import Callable, Generator
from typing import Union

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import End, Game, Lsd
from app.schemas import (
    EndMdResponse,
    EndFourResponse,
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
) -> APIRouter:
    """games ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        end_response_model: ends のレスポンスモデル（md / four で異なる）

    Returns:
        APIRouter: 設定済みの games ルーター
    """
    router = APIRouter()

    @router.get("/games", response_model=ListResponse[GameResponse])
    def list_games(
        limit: int = 50,
        offset: int = 0,
        sort: GameSortField = GameSortField.id,
        order: OrderDirection = OrderDirection.asc,
        # --- フィルタ ---
        # int | None = None: 指定がなければ None（フィルタなし）
        event_id: int | None = None,
        team: str | None = None,    # チーム名の部分一致フィルタ
        db: Session = Depends(get_db),
    ) -> ListResponse[GameResponse]:
        """試合一覧を取得する。

        Args:
            limit: 取得件数の上限
            offset: 取得開始位置
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            event_id: 大会IDで絞り込み（省略可）
            team: チーム名の部分一致で絞り込み（省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[GameResponse]: 総件数・ページネーション情報・試合リスト
        """
        query = db.query(Game)

        # フィルタが指定された場合のみ WHERE 句を追加
        if event_id is not None:
            query = query.filter(Game.event_id == event_id)
        if team is not None:
            # ilike: 大文字小文字を区別しない部分一致（LIKE の case-insensitive 版）
            # | はOR条件（team_red または team_yellow に一致）
            query = query.filter(
                (Game.team_red.ilike(f"%{team}%")) | (Game.team_yellow.ilike(f"%{team}%"))
            )

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Game, sort.value)))

        total = query.count()
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/games/{game_id}", response_model=GameResponse)
    def get_game(
        game_id: int,
        db: Session = Depends(get_db),
    ) -> GameResponse:
        """試合を1件取得する。

        Args:
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
        response_model=ListResponse[end_response_model],
    )
    def list_game_ends(
        game_id: int,
        limit: int = 50,
        offset: int = 0,
        sort: EndSortField = EndSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse:
        """試合に属するエンド一覧を取得する。

        Args:
            game_id: 試合 ID
            limit: 取得件数の上限
            offset: 取得開始位置
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
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/games/{game_id}/lsds", response_model=ListResponse[LsdResponse])
    def list_game_lsds(
        game_id: int,
        limit: int = 50,
        offset: int = 0,
        sort: LsdSortField = LsdSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[LsdResponse]:
        """試合に属する LSD 一覧を取得する。

        Args:
            game_id: 試合 ID
            limit: 取得件数の上限
            offset: 取得開始位置
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
        records = query.offset(offset).limit(limit).all()

        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
