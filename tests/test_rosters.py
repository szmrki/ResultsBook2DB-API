"""
/v1/{md,four}/rosters エンドポイントのテスト。

rosters は md / four でカラム構成が異なる唯一の新テーブルなので、
レスポンスモデルの差分（four: position/is_skip/is_vice、md: gender）と
DB 固有フィルタ（four: is_skip、md: gender）の検証を重視する。

なお Roster モデルは md/four の和集合カラムを持つ。テスト DB は create_all で
全カラムを作るため（= 本番 PostgreSQL 相当）、four 側に gender を INSERT したり
md 側に is_skip を INSERT すること自体は可能だが、レスポンスモデルが該当 DB の
カラムだけに射影することを確認する。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Roster

# ─── テストデータ作成用ヘルパー ────────────────────────────────────────────

def create_event(db: Session, name: str, year: int = 2023, category: str = "Men") -> Event:
    """テスト用の Event レコードを INSERT して返す。

    Args:
        db: テスト用 DB セッション
        name: 大会コード
        year: 開催年
        category: カテゴリ

    Returns:
        Event: 作成した Event オブジェクト（id 採番済み）
    """
    event = Event(name=name, year=year, category=category)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_roster(
    db: Session, event_id: int, team: str, player_name: str, **kwargs: object
) -> Roster:
    """テスト用の Roster レコードを INSERT して返す。

    four 固有（position/is_skip/is_vice）と md 固有（gender）は kwargs で任意に渡す。

    Args:
        db: テスト用 DB セッション
        event_id: 所属大会 ID
        team: チーム名
        player_name: 選手・コーチ名
        **kwargs: role / position / is_skip / is_vice / gender などの任意カラム

    Returns:
        Roster: 作成した Roster オブジェクト（id 採番済み）
    """
    roster = Roster(event_id=event_id, team=team, player_name=player_name, **kwargs)
    db.add(roster)
    db.commit()
    db.refresh(roster)
    return roster


# ─── 1. 空のリスト取得 ────────────────────────────────────────────────────

def test_list_rosters_empty(client: TestClient) -> None:
    """データが 0 件のとき、空リストと total=0 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    response = client.get("/v1/four/rosters")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["data"] == []


# ─── 2. four のレスポンスは position/is_skip/is_vice を含み gender を含まない ──

def test_list_rosters_four_response_fields(client: TestClient, four_db: Session) -> None:
    """four の rosters レスポンスに four 固有カラムのみ含まれることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    create_roster(
        four_db, event_id=event.id, team="SCO", player_name="MOUAT Bruce",
        role="player", position=4, is_skip=1, is_vice=0,
    )

    response = client.get("/v1/four/rosters")

    assert response.status_code == 200
    row = response.json()["data"][0]
    # four 固有カラムを含む
    assert set(row.keys()) == {
        "id", "event_id", "team", "player_name", "role",
        "position", "is_skip", "is_vice",
    }
    # md 固有の gender は含まれない
    assert "gender" not in row
    assert row["is_skip"] == 1
    assert row["position"] == 4


# ─── 3. md のレスポンスは gender を含み four 固有カラムを含まない ──────────────

def test_list_rosters_md_response_fields(client: TestClient, md_db: Session) -> None:
    """md の rosters レスポンスに md 固有カラム（gender）のみ含まれることを確認する。

    Args:
        client: HTTP クライアント
        md_db: md DB セッション
    """
    event = create_event(md_db, name="WMDCC2023", category="MD")
    create_roster(
        md_db, event_id=event.id, team="RUS", player_name="BRYZGALOVA Anastasia",
        role="player", gender="Female",
    )

    response = client.get("/v1/md/rosters")

    assert response.status_code == 200
    row = response.json()["data"][0]
    # md 固有の gender を含む
    assert set(row.keys()) == {
        "id", "event_id", "team", "player_name", "role", "gender",
    }
    # four 固有カラムは含まれない
    assert "is_skip" not in row
    assert "position" not in row
    assert row["gender"] == "Female"


# ─── 4. event_id フィルタ ─────────────────────────────────────────────────

def test_list_rosters_filter_by_event_id(client: TestClient, four_db: Session) -> None:
    """event_id フィルタで対象大会の選手だけに絞れることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event_a = create_event(four_db, name="ECC2023Men")
    event_b = create_event(four_db, name="ECC2024Men", year=2024)
    create_roster(four_db, event_id=event_a.id, team="SCO", player_name="A", role="player")
    create_roster(four_db, event_id=event_b.id, team="ITA", player_name="B", role="player")

    response = client.get(f"/v1/four/rosters?event_id={event_a.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["player_name"] == "A"


# ─── 5. role フィルタ（完全一致） ─────────────────────────────────────────

def test_list_rosters_filter_by_role(client: TestClient, four_db: Session) -> None:
    """role フィルタで player / coach を絞り込めることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    create_roster(four_db, event_id=event.id, team="SCO", player_name="PLAYER", role="player")
    create_roster(four_db, event_id=event.id, team="SCO", player_name="COACH", role="coach")

    response = client.get("/v1/four/rosters?role=coach")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["player_name"] == "COACH"


# ─── 6. four 固有フィルタ is_skip ──────────────────────────────────────────

def test_list_rosters_filter_by_is_skip(client: TestClient, four_db: Session) -> None:
    """four 固有の is_skip フィルタでスキップのみに絞れることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    create_roster(
        four_db, event_id=event.id, team="SCO", player_name="SKIP",
        role="player", is_skip=1, is_vice=0,
    )
    create_roster(
        four_db, event_id=event.id, team="SCO", player_name="LEAD",
        role="player", is_skip=0, is_vice=0,
    )

    response = client.get("/v1/four/rosters?is_skip=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["player_name"] == "SKIP"


# ─── 7. md 固有フィルタ gender ─────────────────────────────────────────────

def test_list_rosters_filter_by_gender(client: TestClient, md_db: Session) -> None:
    """md 固有の gender フィルタで性別を絞り込めることを確認する。

    Args:
        client: HTTP クライアント
        md_db: md DB セッション
    """
    event = create_event(md_db, name="WMDCC2023", category="MD")
    create_roster(
        md_db, event_id=event.id, team="RUS", player_name="FEMALE",
        role="player", gender="Female",
    )
    create_roster(
        md_db, event_id=event.id, team="RUS", player_name="MALE",
        role="player", gender="Male",
    )

    response = client.get("/v1/md/rosters?gender=Male")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["player_name"] == "MALE"


# ─── 8. 単一取得（正常系） ─────────────────────────────────────────────────

def test_get_roster(client: TestClient, four_db: Session) -> None:
    """存在する ID を指定したとき、正しいデータを返すことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    roster = create_roster(
        four_db, event_id=event.id, team="SCO", player_name="MOUAT Bruce",
        role="player", position=4, is_skip=1, is_vice=0,
    )

    response = client.get(f"/v1/four/rosters/{roster.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == roster.id
    assert body["player_name"] == "MOUAT Bruce"
    assert body["is_skip"] == 1


# ─── 9. 単一取得（404） ────────────────────────────────────────────────────

def test_get_roster_not_found(client: TestClient) -> None:
    """存在しない ID を指定したとき、404 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    response = client.get("/v1/four/rosters/99999")

    assert response.status_code == 404
    body = response.json()
    assert body["status_code"] == 404
    assert "not found" in body["detail"].lower()


# ─── 10. 大会配下エンドポイント ────────────────────────────────────────────

def test_list_event_rosters(client: TestClient, four_db: Session) -> None:
    """/events/{id}/rosters が対象大会の選手を返すことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    create_roster(four_db, event_id=event.id, team="SCO", player_name="A", role="player")
    create_roster(four_db, event_id=event.id, team="SCO", player_name="B", role="player")

    response = client.get(f"/v1/four/events/{event.id}/rosters")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    # four 配下のレスポンスも four のレスポンスモデル（gender を含まない）
    assert "gender" not in body["data"][0]
    assert "is_skip" in body["data"][0]


# ─── 11. 大会配下エンドポイント（存在しない大会は 404） ────────────────────────

def test_list_event_rosters_event_not_found(client: TestClient) -> None:
    """存在しない大会 ID を指定したとき、404 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    response = client.get("/v1/four/events/99999/rosters")

    assert response.status_code == 404
    assert response.json()["status_code"] == 404
