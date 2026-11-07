"""
/v1/four/lsds エンドポイントのテスト。

261106 DB で追加された lsds.turn（回転方向）がレスポンスに含まれることと、
turn で絞り込めることを確認する。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Game, Lsd

# ─── テストデータ作成用ヘルパー ────────────────────────────────────────────


def create_game_with_lsds(db: Session) -> Game:
    """1試合分の LSD（2チーム × cw・ccw の4投）を INSERT し、その試合を返す。

    実データと同じく、各チームが cw・ccw を1投ずつ投げた形にする。

    Args:
        db: テスト用 DB セッション

    Returns:
        Game: 作成した試合オブジェクト
    """
    event = Event(name="LSD_EV", category="Men")
    db.add(event)
    db.commit()
    db.refresh(event)

    game = Game(event_id=event.id, team_red="JPN", team_yellow="CAN")
    db.add(game)
    db.commit()
    db.refresh(game)

    db.add_all(
        [
            Lsd(game_id=game.id, team="JPN", player_name="A", distance_cm=10.0, turn="cw"),
            Lsd(game_id=game.id, team="JPN", player_name="B", distance_cm=20.0, turn="ccw"),
            Lsd(game_id=game.id, team="CAN", player_name="C", distance_cm=30.0, turn="cw"),
            Lsd(game_id=game.id, team="CAN", player_name="D", distance_cm=40.0, turn="ccw"),
        ]
    )
    db.commit()
    return game


# ─── turn ──────────────────────────────────────────────────────────────────


def test_get_lsd_includes_turn(client: TestClient, four_db: Session) -> None:
    """単一取得のレスポンスに turn が含まれることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    create_game_with_lsds(four_db)

    # Act: 最初に入れた行（JPN の cw）を取得
    response = client.get("/v1/four/lsds/1")

    # Assert
    assert response.status_code == 200
    assert response.json()["turn"] == "cw"


def test_list_lsds_filter_by_turn(client: TestClient, four_db: Session) -> None:
    """turn=ccw で反時計回りの LSD だけに絞り込めることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    create_game_with_lsds(four_db)

    # Act
    response = client.get("/v1/four/lsds?turn=ccw")

    # Assert: 各チーム1投ずつの2投
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {row["team"] for row in body["data"]} == {"JPN", "CAN"}
    assert all(row["turn"] == "ccw" for row in body["data"])


def test_list_lsds_filter_by_turn_invalid(client: TestClient) -> None:
    """cw / ccw 以外の turn を渡すと 422 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    # Act
    response = client.get("/v1/four/lsds?turn=left")

    # Assert
    assert response.status_code == 422
