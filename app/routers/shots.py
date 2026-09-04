"""shots ルーター。ショットの一覧・単一取得・配下のストーン座標一覧を提供する。"""

from collections.abc import Callable, Generator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from app.models import End, Event, Game, Shot, Stone
from app.pagination import limit_query, offset_query
from app.schemas import (
    ListResponse,
    OrderDirection,
    ShotResponse,
    ShotSortField,
    ShotTurn,
    StoneColor,
    StoneResponse,
    StoneSortField,
)

# percent_score が取りうる5段階の固定値。これ以外は不正値として弾く。
ALLOWED_PERCENT_SCORES = frozenset({0, 25, 50, 75, 100})


def _parse_percent_scores(raw: str) -> list[int]:
    """percent_score のカンマ区切り文字列を整数リストにパースして検証する。

    例: "75,100" → [75, 100]。分析用途で「成功ショットのみ」のような
    複数値フィルタを1リクエストで表現できるようにする。

    Args:
        raw: クエリで渡されたカンマ区切り文字列（例: "75,100"）。

    Returns:
        パース済みの整数リスト（重複は除去せずそのまま IN に渡す）。

    Raises:
        HTTPException: 整数に変換できない、または 5段階（0/25/50/75/100）
            以外の値が含まれる場合に 422 を返す。
    """
    scores: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if token == "":
            # 空要素（例: "75," や ",,"）は不正入力として扱う。
            continue
        try:
            value = int(token)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"percent_score は整数で指定してください（不正な値: {token!r}）",
            ) from None
        if value not in ALLOWED_PERCENT_SCORES:
            raise HTTPException(
                status_code=422,
                detail=(
                    "percent_score は 0 / 25 / 50 / 75 / 100 のいずれかです"
                    f"（不正な値: {value}）"
                ),
            )
        scores.append(value)
    if not scores:
        # カンマだけ・空文字など、有効値が1つもない場合も不正入力とする。
        raise HTTPException(
            status_code=422,
            detail="percent_score に有効な値が指定されていません",
        )
    return scores


def create_router(
    get_db: Callable[[], Generator[Session, None, None]],
    limiter: Limiter,
    rate_limit: str,
) -> APIRouter:
    """shots ルーターを生成して返すファクトリ関数。

    Args:
        get_db: DBセッションを yield するジェネレータ関数（get_md_db / get_four_db）
        limiter: レートリミッターオブジェクト（main.py から渡される）
        rate_limit: レートリミットの上限（例: "100/minute"）。main.py の RATE_LIMIT 定数を渡す

    Returns:
        APIRouter: 設定済みの shots ルーター
    """
    router = APIRouter()

    @router.get(
        "/shots",
        response_model=ListResponse[ShotResponse],
        summary="ショット一覧を取得",
        description=(
            "ショットの一覧を返す。\n\n"
            "> **`percent_score` は 0/25/50/75/100 の離散値**です（連続値ではありません）。"
            "高い値に偏った分布のため、平均値だけでの比較には注意してください。\n\n"
            "> `percent_score` / `turn` の `null` はランダムな欠損ではなく、"
            "`type` が `Through` / `no statistics` の"
            "**成功率を定義できないショット**に対応します。"
        ),
    )
    @limiter.limit(rate_limit)
    def list_shots(
        request: Request,  # noqa: ARG001
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: ShotSortField = ShotSortField.id,
        order: OrderDirection = OrderDirection.asc,
        event_id: int | None = None,
        category: str | None = None,
        game_id: int | None = None,
        end_id: int | None = None,
        number: int | None = None,
        player_name: str | None = None,
        type: str | None = None,
        color: StoneColor | None = None,
        turn: ShotTurn | None = None,
        percent_score: str | None = None,
        db: Session = Depends(get_db),
    ) -> ListResponse[ShotResponse]:
        """ショット一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
            sort: ソート対象カラム名
            order: ソート方向（asc / desc）
            event_id: 大会IDで絞り込み（省略可。shots→ends→games を辿って絞る）
            category: 大会カテゴリで絞り込み（例: "Men" / "Women"、省略可。
                shots→ends→games→events を辿って絞る）
            game_id: 試合IDで絞り込み（省略可。shots→ends を辿って絞る）
            end_id: エンドIDで絞り込み（省略可）
            number: ショット番号で絞り込み（省略可）
            player_name: 選手名の部分一致で絞り込み（省略可）
            type: ショットタイプで絞り込み（省略可）
            color: ストーン色で絞り込み（"red" / "yellow"、省略可）
            turn: 投球のターン（回転）方向で絞り込み（"cw" / "ccw"、省略可）
            percent_score: ショット評価スコアで絞り込み（省略可）。
                カンマ区切りで複数指定できる（例: "75,100" で成功ショットのみ）。
                percent_score は 0 / 25 / 50 / 75 / 100 の5段階固定値で、
                それ以外の値を指定すると 422 を返す。
            db: DB セッション（依存性注入）

        Returns:
            ListResponse[ShotResponse]: 総件数・ページネーション情報・ショットリスト
        """
        query = db.query(Shot)

        # event_id / category / game_id はいずれも End を経由するため、
        # どれか1つでも指定されたら End を1回だけ JOIN する（重複 JOIN を防ぐ）。
        if event_id is not None or category is not None or game_id is not None:
            query = query.join(End, Shot.end_id == End.id)
        # event_id / category はさらに Game を経由する。
        if event_id is not None or category is not None:
            query = query.join(Game, End.game_id == Game.id)
        # category は最上位の Event まで辿る。
        if category is not None:
            query = query.join(Event, Game.event_id == Event.id).filter(
                Event.category == category
            )
        if event_id is not None:
            query = query.filter(Game.event_id == event_id)
        if game_id is not None:
            query = query.filter(End.game_id == game_id)
        if end_id is not None:
            query = query.filter(Shot.end_id == end_id)
        if number is not None:
            query = query.filter(Shot.number == number)
        if player_name is not None:
            query = query.filter(Shot.player_name.ilike(f"%{player_name}%"))
        if type is not None:
            query = query.filter(Shot.type == type)
        if color is not None:
            query = query.filter(Shot.color == color)
        if turn is not None:
            query = query.filter(Shot.turn == turn)
        if percent_score is not None:
            # カンマ区切り文字列（例: "75,100"）を整数リストにパースし、
            # 許可された5段階値のみを受け付けて IN フィルタで絞る。
            scores = _parse_percent_scores(percent_score)
            query = query.filter(Shot.percent_score.in_(scores))

        order_func = asc if order == OrderDirection.asc else desc
        query = query.order_by(order_func(getattr(Shot, sort.value)))
        total = query.count()
        records = cast(list[ShotResponse], query.offset(offset).limit(limit).all())
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    @router.get(
        "/shots/{shot_id}",
        response_model=ShotResponse,
        summary="ショットを1件取得",
        description=(
            "ショットを1件返す。\n\n"
            "> `percent_score` は 0/25/50/75/100 の離散値です。`type` が "
            "`Through` / `no statistics` の場合は成功率が定義できず `null` になります。"
        ),
    )
    @limiter.limit(rate_limit)
    def get_shot(
        request: Request,  # noqa: ARG001
        shot_id: int,
        db: Session = Depends(get_db),
    ) -> ShotResponse:
        """ショットを1件取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
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

    @router.get(
        "/shots/{shot_id}/stones",
        response_model=ListResponse[StoneResponse],
        summary="ショット後のストーン座標一覧を取得",
        description=(
            "指定ショットの**投球後に盤面に残る全ストーン**（最大16行）を返す。\n\n"
            "> **この一覧は「投げた石の着弾点」ではありません。**"
            "その投球で投げられた石は、`shot_order` がこのショットの `number` と"
            "一致する1行です。区別せず集計すると着弾分布が歪みます。\n\n"
            "> `shot_order` の `null` と負値は異常値なので除外してください。"
            "座標は**メートル単位**（`x=0` がセンターライン）。"
        ),
    )
    @limiter.limit(rate_limit)
    def list_shot_stones(
        request: Request,  # noqa: ARG001
        shot_id: int,
        limit: int = limit_query(),
        offset: int = offset_query(),
        sort: StoneSortField = StoneSortField.id,
        order: OrderDirection = OrderDirection.asc,
        db: Session = Depends(get_db),
    ) -> ListResponse[StoneResponse]:
        """ショット後のストーン座標一覧を取得する。

        Args:
            request: slowapi がレートリミットに使用するリクエストオブジェクト（未使用）
            shot_id: ショット ID
            limit: 取得件数の上限（1〜100000）
            offset: 取得開始位置（0以上）
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
        records = cast(list[StoneResponse], query.offset(offset).limit(limit).all())
        return ListResponse(total=total, limit=limit, offset=offset, data=records)

    return router
