"""rosters ルーター。大会出場選手の一覧・単一取得を提供する。

md / four でカラム構成が異なるため、レスポンスモデルを引数で受け取る
（ends ルーターと同じ方針）。md 固有の gender / four 固有の is_skip などの
フィルタは両方定義しておく。該当カラムを持たない DB では対象列が常に NULL の
ため、そのフィルタを指定すると単に0件になる（無害）。
"""

from collections.abc import Callable, Generator
from typing import Union, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import Roster
from app.pagination import limit_query, offset_query
from app.schemas import (
    ListResponse,
    OrderDirection,
    RosterFourResponse,
    RosterMdResponse,
    RosterSortField,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    roster_response_model: type[Union[RosterMdResponse, RosterFourResponse]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """rosters ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        roster_response_model: rosters のレスポンスモデル（md / four で異なる）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの rosters ルーター
    """
    router = APIRouter()

    @router.get("/rosters", response_model=ListResponse[roster_response_model])  # type: ignore[valid-type]
    @limiter.limit(rate_limit)
    def list_rosters(
        request: Request,  # noqa: ARG001
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: RosterSortField = RosterSortField.id,
        order: OrderDirection = OrderDirection.asc,
        event_id: int | None = None,
        team: str | None = None,
        player_name: str | None = None,
        role: str | None = None,
        is_skip: int | None = None,
        is_vice: int | None = None,
        gender: str | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse:
        """出場選手一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            event_id: 大会IDで絞り込み（省略可）
            team: チーム名の部分一致で絞り込み（省略可）
            player_name: 選手名の部分一致で絞り込み（省略可）
            role: 役割の完全一致で絞り込み（"player" / "coach"、省略可）
            is_skip: スキップフラグで絞り込み（0 / 1、four のみ有効、省略可）
            is_vice: バイスフラグで絞り込み（0 / 1、four のみ有効、省略可）
            gender: 性別で絞り込み（"Male" / "Female"、md のみ有効、省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse: 総件数・ページネーション情報・出場選手リスト
        """
        query = db.query(Roster)

        if event_id is not None:
            query = query.filter(Roster.event_id == event_id)
        if team is not None:
            query = query.filter(Roster.team.ilike(f"%{team}%"))
        if player_name is not None:
            query = query.filter(Roster.player_name.ilike(f"%{player_name}%"))
        if role is not None:
            query = query.filter(Roster.role == role)
        if is_skip is not None:
            query = query.filter(Roster.is_skip == is_skip)
        if is_vice is not None:
            query = query.filter(Roster.is_vice == is_vice)
        if gender is not None:
            query = query.filter(Roster.gender == gender)

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Roster, sort.value)))
        total = query.count()
        records = cast(
            list[RosterMdResponse | RosterFourResponse],
            query.offset(offset).limit(limit).all(),
        )
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get("/rosters/{roster_id}", response_model=roster_response_model)
    @limiter.limit(rate_limit)
    def get_roster(
        request: Request,  # noqa: ARG001
        roster_id: int,
        db: Session = Depends(get_db),
    ) -> Roster:
        """出場選手を1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            roster_id: 取得するロスターレコードの ID
            db: DB セッション（依存性注入）

        Returns:
            Roster: 出場選手情報

        Raises:
            HTTPException: 指定 ID のロスターレコードが存在しない場合（404）
        """
        roster = db.query(Roster).filter(Roster.id == roster_id).first()
        if roster is None:
            raise HTTPException(status_code=404, detail="Roster not found")
        return roster

    return router
