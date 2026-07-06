"""
/v1/four/stones エンドポイントのフィルタのテスト。

issue #9 で追加した上位リソース横断フィルタ（event_id / game_id / end_id）が
正しく効くことを確認する。既存の shot_id など下位フィルタも合わせて検証する。

テスト構成:
  events → games → ends → shots → stones の階層を組み、
  各階層のIDで stones を絞り込めることを確認する。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import End, Event, Game, Shot, Stone

# ─── テストデータ作成用ヘルパー ────────────────────────────────────────────


def build_tree(db: Session, name: str, n_stones: int) -> dict:
    """1大会分の events→games→ends→shots→stones ツリーを作り、主要IDを返す。

    1 shot 配下に n_stones 個のストーンを作る。

    Args:
        db: テスト用 DB セッション
        name: 大会コード（unique 制約があるため一意にすること）
        n_stones: shot 配下に作成するストーン数

    Returns:
        dict: event_id / game_id / end_id / shot_id / stone_ids を含む辞書
    """
    event = Event(name=name, year=2023, category="Men")
    db.add(event)
    db.commit()
    db.refresh(event)

    game = Game(event_id=event.id)
    db.add(game)
    db.commit()
    db.refresh(game)

    end = End(game_id=game.id, number=1)
    db.add(end)
    db.commit()
    db.refresh(end)

    shot = Shot(end_id=end.id, number=1, color="red")
    db.add(shot)
    db.commit()
    db.refresh(shot)

    stone_ids = []
    for i in range(n_stones):
        # shot_order は four DB のみ持つ値。i を入れて区別できるようにする。
        stone = Stone(shot_id=shot.id, color="red", shot_order=i + 1, inhouse=1)
        db.add(stone)
        db.commit()
        db.refresh(stone)
        stone_ids.append(stone.id)

    return {
        "event_id": event.id,
        "game_id": game.id,
        "end_id": end.id,
        "shot_id": shot.id,
        "stone_ids": stone_ids,
    }


# ─── event_id フィルタ ────────────────────────────────────────────────────


def test_list_stones_filter_by_event_id(client: TestClient, four_db: Session) -> None:
    """event_id で絞ると、その大会配下のストーンだけが返ることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    a = build_tree(four_db, name="STONE_EV_A", n_stones=3)
    build_tree(four_db, name="STONE_EV_B", n_stones=2)

    # Act
    response = client.get(f"/v1/four/stones?event_id={a['event_id']}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    returned_ids = {row["id"] for row in body["data"]}
    assert returned_ids == set(a["stone_ids"])


# ─── game_id フィルタ ─────────────────────────────────────────────────────


def test_list_stones_filter_by_game_id(client: TestClient, four_db: Session) -> None:
    """game_id で絞ると、その試合配下のストーンだけが返ることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    a = build_tree(four_db, name="STONE_GM_A", n_stones=4)
    build_tree(four_db, name="STONE_GM_B", n_stones=1)

    # Act
    response = client.get(f"/v1/four/stones?game_id={a['game_id']}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    returned_ids = {row["id"] for row in body["data"]}
    assert returned_ids == set(a["stone_ids"])


# ─── end_id フィルタ ──────────────────────────────────────────────────────


def test_list_stones_filter_by_end_id(client: TestClient, four_db: Session) -> None:
    """end_id で絞ると、そのエンド配下のストーンだけが返ることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    a = build_tree(four_db, name="STONE_END_A", n_stones=2)
    build_tree(four_db, name="STONE_END_B", n_stones=3)

    # Act
    response = client.get(f"/v1/four/stones?end_id={a['end_id']}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    returned_ids = {row["id"] for row in body["data"]}
    assert returned_ids == set(a["stone_ids"])


# ─── 上位フィルタ × shot_order 併用 ──────────────────────────────────────


def test_list_stones_filter_event_id_and_shot_order(
    client: TestClient, four_db: Session
) -> None:
    """event_id と shot_order を併用しても JOIN が重複せず正しく絞れることを確認する。

    「大会 × N投目の着弾点」を stones への1リクエストで取得する、という
    issue #9 の主要ユースケースをそのまま検証する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 大会Aに shot_order 1〜3、大会Bにも shot_order 1〜2
    a = build_tree(four_db, name="STONE_SO_A", n_stones=3)
    build_tree(four_db, name="STONE_SO_B", n_stones=2)

    # Act: 大会A かつ shot_order=2
    response = client.get(f"/v1/four/stones?event_id={a['event_id']}&shot_order=2")

    # Assert: shot_order=2 の1件のみ
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["shot_order"] == 2
