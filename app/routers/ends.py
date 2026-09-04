"""ends ルーター。エンドの一覧・単一取得・配下のショット一覧を提供する。"""

from collections.abc import Callable, Generator
from typing import Union, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import End, Game, Shot
from app.pagination import limit_query, offset_query
from app.schemas import (
    EndFourResponse,
    EndMdResponse,
    EndSortField,
    ListResponse,
    OrderDirection,
    ShotResponse,
    ShotSortField,
    StoneColor,
)


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    end_response_model: type[Union[EndMdResponse, EndFourResponse]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """ends ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        end_response_model: ends のレスポンスモデル（md / four で異なる）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの ends ルーター
    """
    router = APIRouter()

    @router.get(
        "/ends",
        response_model=ListResponse[end_response_model],  # type: ignore[valid-type]
        summary="エンド一覧を取得",
        description=(
            "エンドの一覧を返す。\n\n"
            "> **注意: `score_red` / `score_yellow` の `null` は 0 点ではありません。**\n"
            "> コンシード（投了）により**実施されなかったエンド**を表します。"
            "終盤エンドほど多く、0 点として集計すると"
            "「終盤は得点が少ない」という誤った結論になります。"
            "平均得点などを出す際は、これらの行を分母から除外してください。\n\n"
            "> ブランクエンド（`score_red = 0` かつ `score_yellow = 0`）の後の"
            "ハンマー（後攻権）の扱いは **md と four でルールが異なります**。"
        ),
    )
    @limiter.limit(rate_limit)
    def list_ends(
        request: Request,  # noqa: ARG001
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: EndSortField = EndSortField.id,
        order: OrderDirection = OrderDirection.asc,
        event_id: int | None = None,
        game_id: int | None = None,
        number: int | None = None,
        color_hammer: StoneColor | None = None,
        is_power_play: int | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse:
        """エンド一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            game_id: 試合IDで絞り込み（省略可）
            number: エンド番号で絞り込み（省略可）
            color_hammer: ハンマー色で絞り込み（"red" / "yellow"、省略可）
            is_power_play: パワープレイフラグで絞り込み（0 / 1、md のみ有効、省略可）
            db: DB セッション（依存性注入）

        Returns:
            ListResponse: 総件数・ページネーション情報・エンドリスト
        """
        query = db.query(End)

        if event_id is not None:
            query = query.join(Game).filter(Game.event_id == event_id)
        if game_id is not None:
            query = query.filter(End.game_id == game_id)
        if number is not None:
            query = query.filter(End.number == number)
        if color_hammer is not None:
            query = query.filter(End.color_hammer == color_hammer)
        if is_power_play is not None:
            query = query.filter(End.is_power_play == is_power_play)

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(End, sort.value)))
        total = query.count()
        records = cast(
            list[EndMdResponse | EndFourResponse], query.offset(offset).limit(limit).all()
        )
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get(
        "/ends/{end_id}",
        response_model=end_response_model,
        summary="エンドを1件取得",
        description=(
            "エンドを1件返す。\n\n"
            "> `score_red` / `score_yellow` が `null` の場合、それは 0 点ではなく"
            "**コンシードにより実施されなかったエンド**を意味します。"
        ),
    )
    @limiter.limit(rate_limit)
    def get_end(
        request: Request,  # noqa: ARG001
        end_id: int,
        db: Session = Depends(get_db),
    ) -> End:
        """エンドを1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
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

    @router.get(
        "/ends/{end_id}/shots",
        response_model=ListResponse[ShotResponse],
        summary="エンドに属するショット一覧を取得",
        description=(
            "指定エンドに属するショットの一覧を返す。\n\n"
            "> `percent_score` は 0/25/50/75/100 の**離散値**です（連続値ではありません）。"
            "`type` が `Through` / `no statistics` のショットでは"
            "成功率が定義できず `null` になります。"
        ),
    )
    @limiter.limit(rate_limit)
    def list_end_shots(
        request: Request,  # noqa: ARG001
        end_id: int,
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: ShotSortField = ShotSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[ShotResponse]:
        """エンドに属するショット一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            end_id: エンド ID
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
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
        records = cast(list[ShotResponse], query.offset(offset).limit(limit).all())
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
