"""
/v1/four/games エンドポイントのフィルタのテスト。

D-3（issue #11）: team_a と team_b を両方指定したとき、両チームが対戦した試合を
返す（red / yellow の並び順を問わない）ことを確認する。既存の team フィルタ
（片チーム指定）が引き続き動くことも合わせて検証する。

261106 DB で追加された列（date / stage_type / stage / group_name / sheet）による
絞り込みと、date でのソートも確認する。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Game

# ─── テストデータ作成用ヘルパー ────────────────────────────────────────────


def create_event(db: Session, name: str) -> Event:
    """テスト用の Event を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        name: 大会コード（一意にすること）

    Returns:
        Event: 作成した大会オブジェクト
    """
    event = Event(name=name, category="Men")
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_game(
    db: Session,
    event_id: int,
    team_red: str,
    team_yellow: str,
    date: str | None = None,
    stage_type: str | None = None,
    stage: str | None = None,
    group_name: str | None = None,
    sheet: str | None = None,
) -> Game:
    """指定大会配下に、red / yellow のチーム名を持つ Game を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        event_id: 所属大会ID
        team_red: レッド側チーム名
        team_yellow: イエロー側チーム名
        date: 試合日（"YYYY-MM-DD"、省略可）
        stage_type: ステージの分類（"round_robin" など、省略可）
        stage: ステージ名（省略可）
        group_name: グループ名（省略可）
        sheet: シート名（省略可）

    Returns:
        Game: 作成した試合オブジェクト
    """
    game = Game(
        event_id=event_id,
        team_red=team_red,
        team_yellow=team_yellow,
        date=date,
        stage_type=stage_type,
        stage=stage,
        group_name=group_name,
        sheet=sheet,
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


# ─── 対戦カードフィルタ（team_a & team_b） ────────────────────────────────


def test_matchup_matches_regardless_of_color(
    client: TestClient, four_db: Session
) -> None:
    """team_a=JPN & team_b=CAN が、red/yellow どちらの並びの対戦もマッチすることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: JPN vs CAN を red/yellow 逆の2試合＋無関係な1試合
    event = create_event(four_db, name="MATCHUP_EV")
    create_game(four_db, event.id, team_red="JPN", team_yellow="CAN")
    create_game(four_db, event.id, team_red="CAN", team_yellow="JPN")
    create_game(four_db, event.id, team_red="SWE", team_yellow="SUI")

    # Act: JPN と CAN の対戦カードを指定
    response = client.get("/v1/four/games?team_a=JPN&team_b=CAN")

    # Assert: 並び順に関わらず2試合ともマッチ（SWE vs SUI は除外）
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    for row in body["data"]:
        teams = {row["team_red"], row["team_yellow"]}
        assert teams == {"JPN", "CAN"}


def test_matchup_excludes_games_with_only_one_team(
    client: TestClient, four_db: Session
) -> None:
    """片方のチームしか含まない試合は対戦カード指定にマッチしないことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: JPN は含むが対戦相手が CAN でない試合
    event = create_event(four_db, name="MATCHUP_EX_EV")
    create_game(four_db, event.id, team_red="JPN", team_yellow="SWE")
    create_game(four_db, event.id, team_red="JPN", team_yellow="CAN")

    # Act
    response = client.get("/v1/four/games?team_a=JPN&team_b=CAN")

    # Assert: JPN vs CAN の1試合のみ
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    teams = {body["data"][0]["team_red"], body["data"][0]["team_yellow"]}
    assert teams == {"JPN", "CAN"}


def test_matchup_partial_match(client: TestClient, four_db: Session) -> None:
    """team_a / team_b は部分一致でマッチすることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: フルネーム表記の対戦
    event = create_event(four_db, name="MATCHUP_PARTIAL_EV")
    create_game(
        four_db, event.id, team_red="JPN - Japan", team_yellow="CAN - Canada"
    )

    # Act: 部分文字列で指定
    response = client.get("/v1/four/games?team_a=Japan&team_b=Canada")

    # Assert: 部分一致で1試合ヒット
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


def test_team_a_only_is_ignored_as_matchup(
    client: TestClient, four_db: Session
) -> None:
    """team_a だけの指定では対戦カードフィルタが働かない（全件返る）ことを確認する。

    対戦カードは team_a と team_b の両方が揃ったときのみ機能する仕様。
    片方だけの絞り込みには既存の team フィルタを使う想定。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 2試合
    event = create_event(four_db, name="MATCHUP_SINGLE_EV")
    create_game(four_db, event.id, team_red="JPN", team_yellow="CAN")
    create_game(four_db, event.id, team_red="SWE", team_yellow="SUI")

    # Act: team_a だけ指定（team_b なし）
    response = client.get(f"/v1/four/games?event_id={event.id}&team_a=JPN")

    # Assert: 対戦カードフィルタは無効なので、大会内の2試合とも返る
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


# ─── 試合の日時・ステージでの絞り込み（261106 DB で追加） ────────────────────


def test_filter_by_stage_type(client: TestClient, four_db: Session) -> None:
    """stage_type=playoff で、決勝トーナメントの試合だけに絞り込めることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 予選2試合・決勝トーナメント1試合
    event = create_event(four_db, name="STAGE_TYPE_EV")
    create_game(four_db, event.id, "JPN", "CAN", stage_type="round_robin")
    create_game(four_db, event.id, "SWE", "SUI", stage_type="round_robin")
    create_game(four_db, event.id, "JPN", "SWE", stage_type="playoff", stage="Semi-final")

    # Act
    response = client.get("/v1/four/games?stage_type=playoff")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["stage"] == "Semi-final"


def test_filter_by_stage_type_invalid(client: TestClient) -> None:
    """4分類以外の stage_type を渡すと 422 を返すことを確認する。

    stage_type は StageType Enum で受けるので、定義外の値は FastAPI が自動で弾く。

    Args:
        client: HTTP クライアント
    """
    # Act: "final" は分類に無い値
    response = client.get("/v1/four/games?stage_type=final")

    # Assert
    assert response.status_code == 422


def test_filter_by_stage_partial_ignores_case(client: TestClient, four_db: Session) -> None:
    """stage は大文字小文字を区別しない部分一致で、表記ゆれをまとめて拾えることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 準決勝の表記ゆれ3通りと、無関係な1試合
    event = create_event(four_db, name="STAGE_PARTIAL_EV")
    create_game(four_db, event.id, "JPN", "CAN", stage="Semi-final")
    create_game(four_db, event.id, "SWE", "SUI", stage="SEMIFINAL")
    create_game(four_db, event.id, "NOR", "SCO", stage="Semifinal")
    create_game(four_db, event.id, "ITA", "GER", stage="Gold Medal Game")

    # Act
    response = client.get("/v1/four/games?stage=semi")

    # Assert: 準決勝の3試合だけ
    assert response.status_code == 200
    assert response.json()["total"] == 3


def test_filter_by_group_name_and_sheet(client: TestClient, four_db: Session) -> None:
    """group_name と sheet は完全一致で絞り込めることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    event = create_event(four_db, name="GROUP_SHEET_EV")
    create_game(four_db, event.id, "JPN", "CAN", group_name="A", sheet="B")
    create_game(four_db, event.id, "SWE", "SUI", group_name="A", sheet="C")
    create_game(four_db, event.id, "NOR", "SCO", group_name="B", sheet="B")

    # Act
    response = client.get("/v1/four/games?group_name=A&sheet=B")

    # Assert: グループ A かつシート B の1試合だけ
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["team_red"] == "JPN"


def test_filter_by_date_range(client: TestClient, four_db: Session) -> None:
    """date_from / date_to で試合日の範囲を絞り込めることを確認する（両端を含む）。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 3日間に1試合ずつ
    event = create_event(four_db, name="DATE_RANGE_EV")
    create_game(four_db, event.id, "JPN", "CAN", date="2026-10-28")
    create_game(four_db, event.id, "SWE", "SUI", date="2026-10-29")
    create_game(four_db, event.id, "NOR", "SCO", date="2026-10-30")

    # Act: 10/29〜10/30
    response = client.get("/v1/four/games?date_from=2026-10-29&date_to=2026-10-30")

    # Assert
    assert response.status_code == 200
    dates = sorted(row["date"] for row in response.json()["data"])
    assert dates == ["2026-10-29", "2026-10-30"]


def test_sort_by_date_in_event_games(client: TestClient, four_db: Session) -> None:
    """/events/{id}/games でも sort=date で試合日順に並べられることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: id の順と試合日の順を逆にしておく
    event = create_event(four_db, name="SORT_DATE_EV")
    create_game(four_db, event.id, "JPN", "CAN", date="2026-10-30")
    create_game(four_db, event.id, "SWE", "SUI", date="2026-10-28")

    # Act
    response = client.get(f"/v1/four/events/{event.id}/games?sort=date")

    # Assert
    assert response.status_code == 200
    dates = [row["date"] for row in response.json()["data"]]
    assert dates == ["2026-10-28", "2026-10-30"]
