"""
ヘルスチェックエンドポイントのテスト。

テストファイルの命名規則:
  pytest は「test_」で始まるファイルを自動で見つける。
  ファイル内では「test_」で始まる関数がテストとして実行される。

テストの基本構造（AAA パターン）:
  Arrange（準備） : テストに必要なデータや状態を用意する
  Act（実行）     : テスト対象の処理を呼び出す
  Assert（検証）  : 結果が期待通りかを assert で確認する
"""

from fastapi.testclient import TestClient


def test_health_check(client: TestClient) -> None:
    """GET / が 200 を返し、{"status": "ok"} を含むことを確認する。

    Args:
        client: conftest.py の client フィクスチャ（自動で注入される）
    """
    # Act: GET / にリクエストを送る
    response = client.get("/")

    # Assert: ステータスコードと レスポンスボディを確認
    # assert は「式が True でなければテスト失敗」という Python の組み込み構文
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
