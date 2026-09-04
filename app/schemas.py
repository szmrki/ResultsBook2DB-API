"""
Pydantic レスポンスモデルとソートフィールド Enum の定義。

Pydantic とは: API が返す JSON の「型定義」ツール。
  - SQLAlchemy ORM モデル（DBの行）→ Pydantic モデル（JSON）への変換を担う
  - 定義したフィールド以外はレスポンスから自動除外される
  - バリデーション（型チェック）も自動で行われる

Enum（列挙型）とは: 取りうる値をあらかじめ決めておくクラス。
  - FastAPI は Enum 型のクエリパラメータを自動でバリデーション
  - 定義外の値が渡された場合は自動で 422 エラーを返す
"""

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

# ジェネリクス用の型変数
# T = TypeVar("T") と書くことで、ListResponse[EventResponse] や
# ListResponse[GameResponse] のように「中身の型を後から指定できる」クラスを作れる
T = TypeVar("T")


# ─── 基底クラス ──────────────────────────────────────────────────────────────

class ORMBase(BaseModel):
    """ORM モデルからの自動変換を有効にした Pydantic 基底クラス。

    from_attributes=True を設定することで、SQLAlchemy の ORM オブジェクトを
    そのまま Pydantic モデルに変換できる。
    （例: db.query(Event).first() の結果を EventResponse に渡せる）
    """

    model_config = ConfigDict(from_attributes=True)


# ─── 一覧レスポンスの共通ラッパー ─────────────────────────────────────────────

class ListResponse(BaseModel, Generic[T]):
    """一覧取得エンドポイント共通のレスポンスラッパー。

    Generic[T] により、ListResponse[EventResponse] のように
    data の中身の型を指定できる。

    Attributes:
        total: フィルタ後の総件数（ページネーション前）
        limit: 取得件数の上限（リクエスト値）
        offset: 取得開始位置（リクエスト値）
        data: レコードのリスト
    """

    total: int
    limit: int
    offset: int
    data: list[T]


# ─── ソートフィールド Enum ────────────────────────────────────────────────────
# str を継承することで、クエリパラメータの文字列と直接比較できる
# （例: sort="id" → EventSortField.id と一致）

class OrderDirection(str, Enum):
    """ソート方向。"""
    asc = "asc"
    desc = "desc"


class StoneColor(str, Enum):
    """ストーン色。ends / shots / stones の color 系フィルタで共用する。"""
    red = "red"
    yellow = "yellow"


class ShotTurn(str, Enum):
    """投球のターン（回転）方向。"""
    cw = "cw"
    ccw = "ccw"


class EventSortField(str, Enum):
    """events テーブルのソート可能カラム。"""
    id = "id"
    name = "name"  # type: ignore[assignment]
    year = "year"
    category = "category"


class GameSortField(str, Enum):
    """games テーブルのソート可能カラム。"""
    id = "id"
    event_id = "event_id"
    team_red = "team_red"
    team_yellow = "team_yellow"
    final_score_red = "final_score_red"
    final_score_yellow = "final_score_yellow"


class EndSortField(str, Enum):
    """ends テーブルのソート可能カラム。"""
    id = "id"
    game_id = "game_id"
    number = "number"
    score_red = "score_red"
    score_yellow = "score_yellow"


class ShotSortField(str, Enum):
    """shots テーブルのソート可能カラム。"""
    id = "id"
    end_id = "end_id"
    number = "number"
    percent_score = "percent_score"


class StoneSortField(str, Enum):
    """stones テーブルのソート可能カラム。"""
    id = "id"
    shot_id = "shot_id"
    x = "x"
    y = "y"
    distance_from_center = "distance_from_center"
    shot_order = "shot_order"


class LsdSortField(str, Enum):
    """lsds テーブルのソート可能カラム。"""
    id = "id"
    game_id = "game_id"
    distance_cm = "distance_cm"


class StandingSortField(str, Enum):
    """standings テーブルのソート可能カラム。"""
    id = "id"
    event_id = "event_id"
    rank = "rank"
    team = "team"  # type: ignore[assignment]


class RosterSortField(str, Enum):
    """rosters テーブルのソート可能カラム。"""
    id = "id"
    event_id = "event_id"
    team = "team"  # type: ignore[assignment]
    player_name = "player_name"


# ─── レスポンスモデル ─────────────────────────────────────────────────────────
# ORMBase を継承しているので、SQLAlchemy オブジェクトをそのまま渡せる。
# int | None のように書くのは「int か null のどちらでもよい」という意味。

class EventResponse(ORMBase):
    """events テーブルのレスポンスモデル。"""

    id: int
    name: str
    year: int | None
    category: str | None
    # 260714 DB で追加（どちらも一部 NULL）
    location: str | None
    venue: str | None


class GameResponse(ORMBase):
    """games テーブルのレスポンスモデル。"""

    id: int
    event_id: int | None
    page: int | None
    team_red: str | None
    team_yellow: str | None
    final_score_red: int | None
    final_score_yellow: int | None


class EndMdResponse(ORMBase):
    """ends テーブルのレスポンスモデル（md DB 用）。is_power_play を含む。"""

    id: int
    game_id: int | None
    page: int | None
    number: int | None
    color_hammer: str | None
    score_red: int | None
    score_yellow: int | None
    is_power_play: int | None


class EndFourResponse(ORMBase):
    """ends テーブルのレスポンスモデル（four DB 用）。is_power_play を含まない。"""

    id: int
    game_id: int | None
    page: int | None
    number: int | None
    color_hammer: str | None
    score_red: int | None
    score_yellow: int | None


class ShotResponse(ORMBase):
    """shots テーブルのレスポンスモデル。"""

    id: int
    end_id: int | None
    number: int | None
    color: str | None
    team: str | None
    player_name: str | None
    type: str | None
    turn: str | None
    percent_score: int | None


class StoneResponse(ORMBase):
    """stones テーブルのレスポンスモデル。"""

    id: int
    shot_id: int | None
    color: str | None
    x: float | None
    y: float | None
    distance_from_center: float | None
    inhouse: int | None
    insheet: int | None
    # md / four とも保持（未対応の大会分は NULL）
    shot_order: int | None


class LsdResponse(ORMBase):
    """lsds テーブルのレスポンスモデル。"""

    id: int
    game_id: int | None
    team: str | None
    player_name: str | None
    distance_cm: float | None


class StandingResponse(ORMBase):
    """standings テーブルのレスポンスモデル（md / four 共通）。"""

    id: int
    event_id: int | None
    rank: int | None
    team: str | None


class RosterMdResponse(ORMBase):
    """rosters テーブルのレスポンスモデル（md DB 用）。gender を含む。"""

    id: int
    event_id: int | None
    team: str | None
    player_name: str | None
    role: str | None
    gender: str | None


class RosterFourResponse(ORMBase):
    """rosters テーブルのレスポンスモデル（four DB 用）。

    position / is_skip / is_vice を含む。
    """

    id: int
    event_id: int | None
    team: str | None
    player_name: str | None
    role: str | None
    position: int | None
    is_skip: int | None
    is_vice: int | None


# ─── 前提知識ドキュメント（notes） ────────────────────────────────────────────
# DB のレコードではなく、同梱の Markdown を配信するためのモデル。

class NoteDoc(str, Enum):
    """配信する前提知識ドキュメントの名前。

    Enum にしておくことで、定義外の文書名は FastAPI が 422 で弾いてくれる
    （= 任意のファイルパスを URL から渡せないので、パストラバーサル対策も兼ねる）。
    """
    schema = "schema"
    sql_notes = "sql-notes"
    metrics = "metrics"


class NoteResponse(BaseModel):
    """前提知識ドキュメント一覧の1件分。

    Attributes:
        doc: 文書名（"schema" / "sql-notes" / "metrics"）
        description: その文書に何が書いてあるかの一行説明
        url: 本文を取得するための URL
    """

    doc: str
    description: str
    url: str
