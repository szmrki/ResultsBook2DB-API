"""limit 上限（MAX_LIMIT）の境界テスト。

limit の上限を 1000 → 100000 に緩和した（app/pagination.py に集約）。
分析用途で「1大会単位の全 stones を1リクエストで取得する」ことを設計目標にした変更で、
将来また上限をいじったときのリグレッションを防ぐために境界を固定する。

確認すること:
  1. 新上限ちょうど（MAX_LIMIT）は 200 で通る
  2. 新上限超え（MAX_LIMIT + 1）は 422 で拒否される
  3. 旧上限（1000）を超える値が、以前は 422 だったが今は 200 で通る
  4. 下限違反（0）は従来どおり 422
  5. 全リソースで同じ上限が効いている（統一の確認）
"""

import pytest
from fastapi.testclient import TestClient

from app.pagination import MAX_LIMIT

# 一覧取得を持つ代表的なエンドポイント（md / four 両系統・複数リソース）。
# 上限は全リソース一律 MAX_LIMIT で統一されていることを、まとめて確認する。
LIST_ENDPOINTS = [
    "/v1/md/events",
    "/v1/four/events",
    "/v1/four/games",
    "/v1/four/ends",
    "/v1/four/shots",
    "/v1/four/stones",
    "/v1/four/lsds",
]


@pytest.mark.parametrize("endpoint", LIST_ENDPOINTS)
def test_limit_at_max_is_allowed(client: TestClient, endpoint: str) -> None:
    """新上限ちょうど（MAX_LIMIT）は 200 で通ることを確認する。

    データが空でも 200（空の一覧）を返せばよい。ここで検証したいのは
    バリデーションを通過して DB アクセスまで到達すること。
    """
    response = client.get(f"{endpoint}?limit={MAX_LIMIT}")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("endpoint", LIST_ENDPOINTS)
def test_limit_over_max_is_rejected(client: TestClient, endpoint: str) -> None:
    """新上限超え（MAX_LIMIT + 1）は 422 で拒否されることを確認する。"""
    response = client.get(f"{endpoint}?limit={MAX_LIMIT + 1}")
    assert response.status_code == 422, response.text


def test_limit_above_old_max_now_allowed(client: TestClient) -> None:
    """旧上限（1000）を超える 1001 が、以前は 422 だったが今は 200 で通る。

    これが本変更の主目的（上限緩和）を最も直接的に示すケース。
    """
    response = client.get("/v1/md/events?limit=1001")
    assert response.status_code == 200, response.text


def test_limit_under_min_is_rejected(client: TestClient) -> None:
    """下限違反（0）は従来どおり 422 で拒否されることを確認する。"""
    response = client.get("/v1/md/events?limit=0")
    assert response.status_code == 422, response.text
