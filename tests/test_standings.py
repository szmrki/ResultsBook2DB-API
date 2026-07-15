"""
/v1/{md,four}/standings エンドポイントのテスト。

standings は md / four で同一スキーマ（id, event_id, rank, team）なので、
基本は four DB 側で代表して検証する（一覧・単一・404・フィルタ・ソート）。
大会配下エンドポイント /events/{event_id}/standings も併せて確認する。
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event, Standing

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


def create_standing(db: Session, event_id: int, rank: int, team: str) -> Standing:
    """テスト用の Standing レコードを INSERT して返す。

    Args:
        db: テスト用 DB セッション
        event_id: 所属大会 ID
        rank: 順位
        team: チーム名

    Returns:
        Standing: 作成した Standing オブジェクト（id 採番済み）
    """
    standing = Standing(event_id=event_id, rank=rank, team=team)
    db.add(standing)
    db.commit()
    db.refresh(standing)
    return standing


# ─── 1. 空のリスト取得 ────────────────────────────────────────────────────

def test_list_standings_empty(client: TestClient) -> None:
    """データが 0 件のとき、空リストと total=0 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    response = client.get("/v1/four/standings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["data"] == []


# ─── 2. データあり一覧取得 ────────────────────────────────────────────────

def test_list_standings_with_data(client: TestClient, four_db: Session) -> None:
    """INSERT したデータが一覧に返り、各フィールドが正しいことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    create_standing(four_db, event_id=event.id, rank=1, team="SCO")
    create_standing(four_db, event_id=event.id, rank=2, team="SUI")

    response = client.get("/v1/four/standings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    first = body["data"][0]
    # レスポンスモデルの4フィールドが揃っているか
    assert set(first.keys()) == {"id", "event_id", "rank", "team"}
    assert first["rank"] == 1
    assert first["team"] == "SCO"


# ─── 3. event_id フィルタ ─────────────────────────────────────────────────

def test_list_standings_filter_by_event_id(client: TestClient, four_db: Session) -> None:
    """event_id フィルタで対象大会の順位だけに絞れることを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event_a = create_event(four_db, name="ECC2023Men")
    event_b = create_event(four_db, name="ECC2024Men", year=2024)
    create_standing(four_db, event_id=event_a.id, rank=1, team="SCO")
    create_standing(four_db, event_id=event_b.id, rank=1, team="ITA")

    response = client.get(f"/v1/four/standings?event_id={event_a.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["team"] == "SCO"


# ─── 4. team 部分一致フィルタ ─────────────────────────────────────────────

def test_list_standings_filter_by_team(client: TestClient, four_db: Session) -> None:
    """team の部分一致フィルタが機能することを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    create_standing(four_db, event_id=event.id, rank=1, team="SCO")
    create_standing(four_db, event_id=event.id, rank=2, team="SUI")

    # 部分一致（大文字小文字を無視）
    response = client.get("/v1/four/standings?team=sc")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["team"] == "SCO"


# ─── 5. 単一取得（正常系） ─────────────────────────────────────────────────

def test_get_standing(client: TestClient, four_db: Session) -> None:
    """存在する ID を指定したとき、正しいデータを返すことを確認する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    standing = create_standing(four_db, event_id=event.id, rank=3, team="ITA")

    response = client.get(f"/v1/four/standings/{standing.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == standing.id
    assert body["rank"] == 3
    assert body["team"] == "ITA"


# ─── 6. 単一取得（404） ────────────────────────────────────────────────────

def test_get_standing_not_found(client: TestClient) -> None:
    """存在しない ID を指定したとき、404 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    response = client.get("/v1/four/standings/99999")

    assert response.status_code == 404
    body = response.json()
    assert body["status_code"] == 404
    assert "not found" in body["detail"].lower()


# ─── 7. 大会配下エンドポイント（rank 昇順デフォルト） ────────────────────────

def test_list_event_standings_default_sort_by_rank(
    client: TestClient, four_db: Session
) -> None:
    """/events/{id}/standings が rank 昇順で返ることを確認する。

    INSERT 順を rank 昇順と逆にしておき、デフォルトソートが rank であることを検証する。

    Args:
        client: HTTP クライアント
        four_db: four DB セッション
    """
    event = create_event(four_db, name="ECC2023Men")
    # あえて rank の降順で INSERT する（id 順 != rank 順にする）
    create_standing(four_db, event_id=event.id, rank=3, team="ITA")
    create_standing(four_db, event_id=event.id, rank=1, team="SCO")
    create_standing(four_db, event_id=event.id, rank=2, team="SUI")

    response = client.get(f"/v1/four/events/{event.id}/standings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    # デフォルトは rank 昇順
    assert [d["rank"] for d in body["data"]] == [1, 2, 3]
    assert body["data"][0]["team"] == "SCO"


# ─── 8. 大会配下エンドポイント（存在しない大会は 404） ────────────────────────

def test_list_event_standings_event_not_found(client: TestClient) -> None:
    """存在しない大会 ID を指定したとき、404 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    response = client.get("/v1/four/events/99999/standings")

    assert response.status_code == 404
    assert response.json()["status_code"] == 404


# ─── 9. md 側でも同一スキーマで動く ───────────────────────────────────────

def test_list_standings_md(client: TestClient, md_db: Session) -> None:
    """md DB でも standings が同一スキーマで取得できることを確認する。

    Args:
        client: HTTP クライアント
        md_db: md DB セッション
    """
    event = create_event(md_db, name="WMDCC2023", category="MD")
    create_standing(md_db, event_id=event.id, rank=1, team="RUS")

    response = client.get("/v1/md/standings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert set(body["data"][0].keys()) == {"id", "event_id", "rank", "team"}
    assert body["data"][0]["team"] == "RUS"
