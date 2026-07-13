"""
/v1/four/shots エンドポイントのフィルタのテスト。

issue #9 で追加した上位リソース横断フィルタ（event_id / category / game_id）が
正しく効くことを確認する。既存の end_id など下位フィルタも合わせて検証する。

テスト構成:
  events → games → ends → shots という階層を実データに近い形で組み、
  各階層のIDやカテゴリで shots を絞り込めることを確認する。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import End, Event, Game, Shot

# ─── テストデータ作成用ヘルパー ────────────────────────────────────────────
# events → games → ends → shots の階層を1関数で組み立てられるようにする。
# 各ヘルパーは作成したオブジェクト（id 採番済み）を返す。


def create_event(db: Session, name: str, category: str = "Men") -> Event:
    """テスト用の Event を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        name: 大会コード（unique 制約があるためテストごとに一意にする）
        category: カテゴリ（"Men" / "Women" など）

    Returns:
        Event: 作成した大会オブジェクト
    """
    event = Event(name=name, year=2023, category=category)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_game(db: Session, event_id: int) -> Game:
    """指定大会配下に Game を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        event_id: 所属大会ID

    Returns:
        Game: 作成した試合オブジェクト
    """
    game = Game(event_id=event_id)
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


def create_end(db: Session, game_id: int, number: int = 1) -> End:
    """指定試合配下に End を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        game_id: 所属試合ID
        number: エンド番号

    Returns:
        End: 作成したエンドオブジェクト
    """
    end = End(game_id=game_id, number=number)
    db.add(end)
    db.commit()
    db.refresh(end)
    return end


def create_shot(db: Session, end_id: int, number: int = 1) -> Shot:
    """指定エンド配下に Shot を INSERT して返す。

    Args:
        db: テスト用 DB セッション
        end_id: 所属エンドID
        number: ショット番号

    Returns:
        Shot: 作成したショットオブジェクト
    """
    shot = Shot(end_id=end_id, number=number, color="red")
    db.add(shot)
    db.commit()
    db.refresh(shot)
    return shot


def build_tree(db: Session, name: str, category: str, n_shots: int) -> dict:
    """1大会分の events→games→ends→shots ツリーを作り、主要IDを返す。

    Args:
        db: テスト用 DB セッション
        name: 大会コード（一意にすること）
        category: 大会カテゴリ
        n_shots: 作成するショット数（すべて同じエンド配下に作る）

    Returns:
        dict: event_id / game_id / end_id / shot_ids を含む辞書
    """
    event = create_event(db, name=name, category=category)
    game = create_game(db, event_id=event.id)
    end = create_end(db, game_id=game.id)
    shot_ids = [create_shot(db, end_id=end.id, number=i).id for i in range(1, n_shots + 1)]
    return {
        "event_id": event.id,
        "game_id": game.id,
        "end_id": end.id,
        "shot_ids": shot_ids,
    }


# ─── event_id フィルタ ────────────────────────────────────────────────────


def test_list_shots_filter_by_event_id(client: TestClient, four_db: Session) -> None:
    """event_id で絞ると、その大会配下のショットだけが返ることを確認する。

    issue #9 では event_id が無視され全件返っていた。修正後は絞れるはず。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 別々の大会を2つ作る（片方3投、片方2投）
    a = build_tree(four_db, name="EVENT_A", category="Men", n_shots=3)
    build_tree(four_db, name="EVENT_B", category="Women", n_shots=2)

    # Act
    response = client.get(f"/v1/four/shots?event_id={a['event_id']}")

    # Assert: 大会Aの3投だけが返る
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    returned_ids = {row["id"] for row in body["data"]}
    assert returned_ids == set(a["shot_ids"])


# ─── category フィルタ ────────────────────────────────────────────────────


def test_list_shots_filter_by_category(client: TestClient, four_db: Session) -> None:
    """category で絞ると、そのカテゴリの大会配下のショットだけが返ることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: Men と Women を1大会ずつ
    build_tree(four_db, name="MEN_EV", category="Men", n_shots=2)
    women = build_tree(four_db, name="WOMEN_EV", category="Women", n_shots=4)

    # Act
    response = client.get("/v1/four/shots?category=Women")

    # Assert: Women の4投だけ
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    returned_ids = {row["id"] for row in body["data"]}
    assert returned_ids == set(women["shot_ids"])


# ─── game_id フィルタ（既存機能の回帰確認） ──────────────────────────────


def test_list_shots_filter_by_game_id(client: TestClient, four_db: Session) -> None:
    """game_id で絞ると、その試合配下のショットだけが返ることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange
    a = build_tree(four_db, name="GAME_A", category="Men", n_shots=3)
    build_tree(four_db, name="GAME_B", category="Men", n_shots=2)

    # Act
    response = client.get(f"/v1/four/shots?game_id={a['game_id']}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    returned_ids = {row["id"] for row in body["data"]}
    assert returned_ids == set(a["shot_ids"])


# ─── フィルタ併用（event_id × number） ────────────────────────────────────


def test_list_shots_filter_event_id_and_number(
    client: TestClient, four_db: Session
) -> None:
    """event_id と number を併用しても JOIN が重複せず正しく絞れることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 大会Aに number 1〜3 の3投、大会Bにも number 1 の1投
    a = build_tree(four_db, name="COMBO_A", category="Men", n_shots=3)
    build_tree(four_db, name="COMBO_B", category="Men", n_shots=1)

    # Act: 大会A かつ number=2
    response = client.get(f"/v1/four/shots?event_id={a['event_id']}&number=2")

    # Assert: number=2 の1投のみ
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["number"] == 2


# ─── percent_score フィルタ（複数値指定・バリデーション） ──────────────────
# D-1（issue #11）: percent_score は 0/25/50/75/100 の5段階固定値。
# カンマ区切りで複数値を指定して IN フィルタで絞れることを確認する。


def _make_shots_with_scores(db: Session, scores: list[int]) -> int:
    """指定した percent_score を持つ shots を1エンド配下に作り、event_id を返す。

    Args:
        db: テスト用 DB セッション
        scores: 作成する各 shot の percent_score のリスト

    Returns:
        作成した大会の event_id（テストで絞り込みの起点に使う）
    """
    event = create_event(db, name=f"SCORE_EV_{scores}")
    game = create_game(db, event_id=event.id)
    end = create_end(db, game_id=game.id)
    for i, score in enumerate(scores, start=1):
        shot = Shot(end_id=end.id, number=i, color="red", percent_score=score)
        db.add(shot)
    db.commit()
    return event.id


def test_list_shots_filter_percent_score_multiple(
    client: TestClient, four_db: Session
) -> None:
    """percent_score=75,100 で該当する2値のショットのみ返すことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    # Arrange: 5段階すべてを1つずつ作る
    event_id = _make_shots_with_scores(four_db, [0, 25, 50, 75, 100])

    # Act: 成功ショット（75 と 100）だけを取得
    response = client.get(f"/v1/four/shots?event_id={event_id}&percent_score=75,100")

    # Assert: 75 と 100 の2件のみ
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert sorted(row["percent_score"] for row in body["data"]) == [75, 100]


def test_list_shots_filter_percent_score_single(
    client: TestClient, four_db: Session
) -> None:
    """percent_score=100 の単一値指定でも正しく絞れることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event_id = _make_shots_with_scores(four_db, [0, 50, 100, 100])

    response = client.get(f"/v1/four/shots?event_id={event_id}&percent_score=100")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(row["percent_score"] == 100 for row in body["data"])


def test_list_shots_filter_percent_score_invalid_value(
    client: TestClient, four_db: Session
) -> None:
    """5段階以外の値（例: 80）を指定すると 422 を返すことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event_id = _make_shots_with_scores(four_db, [100])

    response = client.get(f"/v1/four/shots?event_id={event_id}&percent_score=80")

    assert response.status_code == 422


def test_list_shots_filter_percent_score_not_integer(
    client: TestClient, four_db: Session
) -> None:
    """整数に変換できない値を指定すると 422 を返すことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event_id = _make_shots_with_scores(four_db, [100])

    response = client.get(f"/v1/four/shots?event_id={event_id}&percent_score=abc")

    assert response.status_code == 422
