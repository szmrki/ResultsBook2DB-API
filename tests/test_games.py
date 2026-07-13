"""
/v1/four/games エンドポイントの対戦カードフィルタのテスト。

D-3（issue #11）: team_a と team_b を両方指定したとき、両チームが対戦した試合を
返す（red / yellow の並び順を問わない）ことを確認する。既存の team フィルタ
（片チーム指定）が引き続き動くことも合わせて検証する。
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


def create_game(db: Session, event_id: int, team_red: str, team_yellow: str) -> Game:
    """指定大会配下に、red / yellow のチーム名を持つ Game を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        event_id: 所属大会ID
        team_red: レッド側チーム名
        team_yellow: イエロー側チーム名

    Returns:
        Game: 作成した試合オブジェクト
    """
    game = Game(event_id=event_id, team_red=team_red, team_yellow=team_yellow)
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
