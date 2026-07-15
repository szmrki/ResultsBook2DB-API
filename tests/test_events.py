"""
/v1/md/events エンドポイントのテスト。

テストで確認すること:
  1. データが空のときに正しいレスポンスを返すか
  2. データがあるときに正しく返せるか
  3. 存在しない ID を指定したとき 404 を返すか
  4. 不正なパラメータを渡したとき 422 を返すか
  5. ページネーション（limit / offset）が正しく動くか
  6. ソート（sort / order）が正しく動くか
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Event

# ─── テストデータ作成用ヘルパー ────────────────────────────────────────────
# テスト関数の中に書いても良いが、複数のテストで使い回すので関数にまとめる。
# pytest のフィクスチャではなく普通の関数として定義する（yield を使わないため）。

def create_event(
    db: Session,
    name: str,
    year: int = 2023,
    category: str = "MD",
    location: str | None = None,
    venue: str | None = None,
) -> Event:
    """テスト用の Event レコードを DB に INSERT して返す。

    Args:
        db: テスト用 DB セッション
        name: 大会コード（例: WMDCC2023）
        year: 開催年
        category: カテゴリ
        location: 開催地（省略可）
        venue: 会場名（省略可）

    Returns:
        Event: 作成した Event オブジェクト（id が採番済み）
    """
    event = Event(name=name, year=year, category=category, location=location, venue=venue)
    db.add(event)
    db.commit()
    # commit 後は DB に保存された最新の状態（id など）を Python オブジェクトに反映する
    db.refresh(event)
    return event


# ─── 1. 空のリスト取得 ────────────────────────────────────────────────────

def test_list_events_empty(client: TestClient) -> None:
    """データが 0 件のとき、空リストと total=0 を返すことを確認する。

    Args:
        client: conftest.py の client フィクスチャ
    """
    # Act
    response = client.get("/v1/md/events")

    # Assert
    assert response.status_code == 200
    body = response.json()
    # total / limit / offset / data の4キーを持つ ListResponse 形式か確認
    assert body["total"] == 0
    assert body["data"] == []
    assert body["limit"] == 50   # デフォルト値
    assert body["offset"] == 0   # デフォルト値


# ─── 2. データあり一覧取得 ────────────────────────────────────────────────

def test_list_events_with_data(client: TestClient, md_db: Session) -> None:
    """INSERT したデータが一覧に返ってくることを確認する。

    2つのフィクスチャを同時に受け取れる。
    pytest は引数の名前を見て自動的に対応するフィクスチャを注入する。

    Args:
        client: HTTP クライアント
        md_db: DB に直接 INSERT するためのセッション
    """
    # Arrange: テストデータを2件 INSERT する
    create_event(md_db, name="WMDCC2023", year=2023, category="MD")
    create_event(md_db, name="WMDCC2024", year=2024, category="MD")

    # Act
    response = client.get("/v1/md/events")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["data"]) == 2
    # 最初のレコードの内容を確認
    assert body["data"][0]["name"] == "WMDCC2023"
    assert body["data"][0]["year"] == 2023


# ─── 3. 単一取得（正常系） ─────────────────────────────────────────────────

def test_get_event(client: TestClient, md_db: Session) -> None:
    """存在する ID を指定したとき、正しいデータを返すことを確認する。

    Args:
        client: HTTP クライアント
        md_db: DB セッション
    """
    # Arrange
    event = create_event(md_db, name="WMDCC2023", year=2023, category="MD")

    # Act: create_event が返したオブジェクトの id を使う
    response = client.get(f"/v1/md/events/{event.id}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == event.id
    assert body["name"] == "WMDCC2023"
    assert body["year"] == 2023
    assert body["category"] == "MD"


# ─── 3b. 単一取得で location / venue が返る（260714 で追加） ────────────────

def test_get_event_includes_location_and_venue(client: TestClient, md_db: Session) -> None:
    """260714 で追加された location / venue がレスポンスに含まれることを確認する。

    Args:
        client: HTTP クライアント
        md_db: DB セッション
    """
    # Arrange
    event = create_event(
        md_db, name="ECC2023Men", year=2023, category="Men",
        location="Aberdeen, Scotland", venue="Curl Aberdeen",
    )

    # Act
    response = client.get(f"/v1/md/events/{event.id}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Aberdeen, Scotland"
    assert body["venue"] == "Curl Aberdeen"


def test_get_event_location_venue_nullable(client: TestClient, md_db: Session) -> None:
    """location / venue 未設定の大会では null が返ることを確認する。

    Args:
        client: HTTP クライアント
        md_db: DB セッション
    """
    # Arrange: location / venue を渡さない
    event = create_event(md_db, name="WMDCC2023", year=2023, category="MD")

    # Act
    response = client.get(f"/v1/md/events/{event.id}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["location"] is None
    assert body["venue"] is None


# ─── 4. 単一取得（404） ────────────────────────────────────────────────────

def test_get_event_not_found(client: TestClient) -> None:
    """存在しない ID を指定したとき、404 を返すことを確認する。

    Args:
        client: HTTP クライアント
    """
    # Act: 絶対に存在しない ID を指定
    response = client.get("/v1/md/events/99999")

    # Assert
    assert response.status_code == 404
    # main.py のカスタムエラーハンドラで {"detail": "...", "status_code": 404} になる
    body = response.json()
    assert body["status_code"] == 404
    assert "not found" in body["detail"].lower()


# ─── 5. バリデーションエラー（422） ───────────────────────────────────────

def test_list_events_invalid_sort(client: TestClient) -> None:
    """存在しないソートキーを渡したとき、422 を返すことを確認する。

    sort パラメータは EventSortField Enum で定義されており、
    定義外の値を渡すと FastAPI が自動で 422 を返す。

    Args:
        client: HTTP クライアント
    """
    # Act: sort に無効な値を渡す
    response = client.get("/v1/md/events?sort=invalid_column")

    # Assert
    assert response.status_code == 422


# ─── 6. ページネーション ──────────────────────────────────────────────────

def test_list_events_pagination(client: TestClient, md_db: Session) -> None:
    """limit と offset が正しく機能することを確認する。

    5件 INSERT して limit=2, offset=2 で取得すると
    3件目・4件目だけが返ってくることを確認する。

    Args:
        client: HTTP クライアント
        md_db: DB セッション
    """
    # Arrange: 5件 INSERT
    for i in range(1, 6):
        create_event(md_db, name=f"EVENT{i:04d}", year=2020 + i)

    # Act: 3件目から2件取得（0始まりなので offset=2）
    response = client.get("/v1/md/events?limit=2&offset=2&sort=id&order=asc")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5        # フィルタ前の総件数は5件
    assert len(body["data"]) == 2    # 取得できるのは2件
    assert body["data"][0]["name"] == "EVENT0003"
    assert body["data"][1]["name"] == "EVENT0004"


# ─── 7. ソート ────────────────────────────────────────────────────────────

def test_list_events_sort_by_year_desc(client: TestClient, md_db: Session) -> None:
    """year の降順ソートが正しく機能することを確認する。

    Args:
        client: HTTP クライアント
        md_db: DB セッション
    """
    # Arrange
    create_event(md_db, name="OLD_EVENT", year=2020)
    create_event(md_db, name="NEW_EVENT", year=2024)

    # Act
    response = client.get("/v1/md/events?sort=year&order=desc")

    # Assert
    assert response.status_code == 200
    data = response.json()["data"]
    # 降順なので 2024 が先に来る
    assert data[0]["year"] == 2024
    assert data[1]["year"] == 2020
