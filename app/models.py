"""
SQLAlchemy ORMモデル定義。
DBの各テーブルをPythonクラスとして表現する。

テーブル構造:
    events（大会）
      └── games（試合）
            ├── ends（エンド）
            │     └── shots（投球）
            │           └── stones（ストーン座標）
            └── lsds（LSD記録）

md DB / four DB は同じ6テーブル構成を共有。
唯一の差異は ends.is_power_play（md のみ使用、four では常に NULL）。
"""

from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, relationship

# database.py で定義した Base（ORMモデルの基底クラス）をインポート
# すべてのモデルはこの Base を継承することで SQLAlchemy に認識される
from app.database import Base


class Event(Base):
    """大会テーブル（最上位）。

    Attributes:
        id: 大会ID（主キー、自動採番）
        name: 大会コード（例: WMDCC2023）、重複不可
        year: 開催年
        category: カテゴリ（MD / Men / Women / Junior Men / Junior Women）
        games: この大会に属する試合一覧（relationship）
    """

    # SQLAlchemy に対応するテーブル名を指定
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    year = Column(Integer)
    category = Column(String)

    # relationship: games テーブルと紐づけ
    #   back_populates="event" → Game モデル側の .event 属性と対応
    #   cascade="all, delete-orphan" → この大会を削除すると配下の試合も連鎖削除
    games: Mapped[list["Game"]] = relationship(
        "Game", back_populates="event", cascade="all, delete-orphan"
    )


class Game(Base):
    """試合テーブル。1試合のサマリーを格納。

    team_red / team_yellow はストーンの色に対応（チームの所属カラー）。

    Attributes:
        id: 試合ID（主キー）
        event_id: 所属大会ID（events.id への外部キー）
        page: ソース元スコアシートのページ番号
        team_red: レッドストーン側チーム名（例: JPN - Japan）
        team_yellow: イエローストーン側チーム名
        final_score_red: レッド側最終スコア
        final_score_yellow: イエロー側最終スコア
        event: 所属大会オブジェクト（relationship）
        ends: この試合のエンド一覧（relationship）
        lsds: この試合のLSD記録一覧（relationship）
    """

    __tablename__ = "games"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ForeignKey("events.id") → events テーブルの id カラムを参照
    # ondelete="CASCADE"      → DB側でも連鎖削除を有効化
    # index=True → 親IDで子を絞り込むクエリ（games?event_id=...）を高速化する
    #   PostgreSQL は FK 制約を張っても参照側に自動でインデックスを作らないため明示する
    event_id = Column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    page = Column(Integer)
    team_red = Column(String)
    team_yellow = Column(String)
    final_score_red = Column(Integer)
    final_score_yellow = Column(Integer)

    # 親テーブル（events）への参照
    event: Mapped["Event"] = relationship("Event", back_populates="games")
    # 子テーブル（ends / lsds）への参照
    ends: Mapped[list["End"]] = relationship(
        "End", back_populates="game", cascade="all, delete-orphan"
    )
    lsds: Mapped[list["Lsd"]] = relationship(
        "Lsd", back_populates="game", cascade="all, delete-orphan"
    )


class End(Base):
    """エンドテーブル。エンドごとのスコアとハンマー情報を格納。

    通常は1試合8〜10エンド。延長は理論上何エンドでも続く（既存データでは最大12エンド）。

    Attributes:
        id: エンドID（主キー）
        game_id: 所属試合ID（games.id への外部キー）
        page: ソース元ページ番号
        number: エンド番号（1〜）
        color_hammer: ハンマー保持チームのストーン色（"red" / "yellow"）
        score_red: そのエンドのレッド得点
        score_yellow: そのエンドのイエロー得点
        is_power_play: パワープレイフラグ（1=ON, 0=OFF）。md DB のみ使用、four DB では NULL
        game: 所属試合オブジェクト（relationship）
        shots: このエンドの投球一覧（relationship）
    """

    __tablename__ = "ends"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # index=True → ends?game_id=... での絞り込みを高速化
    game_id = Column(
        Integer, ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    page = Column(Integer)
    number = Column(Integer)
    color_hammer = Column(String)
    score_red = Column(Integer)
    score_yellow = Column(Integer)
    # md DB 専用カラム。four DB では常に NULL のため nullable（デフォルト）のまま
    is_power_play = Column(Integer)

    game: Mapped["Game"] = relationship("Game", back_populates="ends")
    shots: Mapped[list["Shot"]] = relationship(
        "Shot", back_populates="end", cascade="all, delete-orphan"
    )


class Shot(Base):
    """投球テーブル。1エンドにつき最大16投の投球データを格納。

    Attributes:
        id: 投球ID（主キー）
        end_id: 所属エンドID（ends.id への外部キー）
        number: 投球番号（1〜16）
        color: 投球チームのストーン色（"red" / "yellow"）
        team: チーム名（略称）
        player_name: 投球選手名（NULL あり）
        type: ショットタイプ（Draw / Guard / Take-out など、NULL あり）
        turn: ターン方向（"cw"=時計回り / "ccw"=反時計回り）
        percent_score: 成功率スコア（0, 25, 50, 75,100）
        end: 所属エンドオブジェクト（relationship）
        stones: この投球後のストーン座標一覧（relationship）
    """

    __tablename__ = "shots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # index=True → shots?end_id=... での絞り込みを高速化（shots は約4.5万行）
    end_id = Column(Integer, ForeignKey("ends.id", ondelete="CASCADE"), index=True)
    number = Column(Integer)
    color = Column(String)
    team = Column(String)
    player_name = Column(String)   # スコアシートのみデータでは NULL
    type = Column(String)          # ショットタイプ（NULL あり）
    turn = Column(String)
    percent_score = Column(Integer)

    end: Mapped["End"] = relationship("End", back_populates="shots")
    stones: Mapped[list["Stone"]] = relationship(
        "Stone", back_populates="shot", cascade="all, delete-orphan"
    )


class Stone(Base):
    """ストーン座標テーブル。各投球後にシート上に存在する全ストーンの座標を格納。

    1投球につき最大16レコード（シート上に残る全ストーン分）。
    座標系はシートのセンターラインを原点とした単位（フィート）。

    Attributes:
        id: ストーンID（主キー）
        shot_id: 対応投球ID（shots.id への外部キー）
        color: ストーンの色（"red" / "yellow"）
        x: 横方向座標（約 -2.24〜+2.26 ft）
        y: 縦方向座標（約 31.97〜40.51 ft）
        distance_from_center: センター（ティー）からの距離（フィート）
        inhouse: ハウス内フラグ（1=ハウス内, 0=ハウス外）
        insheet: シート内フラグ（1=シート内, 0=シート外）
        shot_order: このストーンが何投目に投げられたかを示す投球順。
            盤面に残る各ストーンの由来投球を保持する。
            現状は four DB のみ保持（md DB では NULL、今後対応予定）
        shot: 対応投球オブジェクト（relationship）
    """

    __tablename__ = "stones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # index=True → stones?shot_id=... での絞り込みを高速化
    #   stones は約72万行と最大のテーブルなので、未インデックスだと毎回フルスキャンになる
    shot_id = Column(Integer, ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    color = Column(String)
    x = Column(Float)
    y = Column(Float)
    distance_from_center = Column(Float)
    inhouse = Column(Integer)
    insheet = Column(Integer)
    # 片方のDBのみ持つカラムは nullable にしておく（is_power_play と同じ方針）
    # 移行スクリプトは models.py ∩ SQLite の積集合を移すため、列が無いDBでは自動で NULL になる
    shot_order = Column(Integer)

    shot: Mapped["Shot"] = relationship("Shot", back_populates="stones")


class Lsd(Base):
    """LSD（Last Stone Draw）テーブル。試合前のハンマー権決定投球の記録。

    試合開始前に両チームが行い、ティーに近づけた方がハンマー（後攻）を得る。

    Attributes:
        id: LSD ID（主キー）
        game_id: 対応試合ID（games.id への外部キー）
        team: チーム名
        player_name: 投球選手名（↻記号でターン方向を示す場合あり/これは今後改善する）
        distance_cm: ティーからの距離（cm、範囲: 0.1〜199.6）
        game: 対応試合オブジェクト（relationship）
    """

    __tablename__ = "lsds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # index=True → game_id での絞り込みを高速化
    game_id = Column(
        Integer, ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    team = Column(String)
    player_name = Column(String)
    distance_cm = Column(Float)

    game: Mapped["Game"] = relationship("Game", back_populates="lsds")
