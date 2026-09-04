"""
前提知識ドキュメント配信エンドポイント（/v1/notes）のテスト。

このエンドポイントが存在する理由:
  rb2db には「知らないと必ず間違える」性質がいくつもある
  （ends の NULL がコンシード由来である、stones.shot_order に負値が混ざる、等）。
  MCP サーバー利用者は同じ知識を MCP リソースとして受け取れるが、
  REST API 利用者にはその経路がなかった。/v1/notes はその差を埋めるもの。

ここで守りたいこと:
  1. 3種類の文書がすべて配信されていること（欠けたら利用者が前提を知れない）
  2. 定義外の文書名を受け付けないこと（＝任意のファイルを読み出せない）
  3. 一覧に載っている URL が実際に取得できること（リンク切れ防止）
  4. 「最重要の落とし穴」が本文に載り続けていること（知識の空洞化防止）
"""

import pytest
from fastapi.testclient import TestClient

# 配信されているはずの文書名。増減したらこのテストも更新する。
EXPECTED_DOCS = ["schema", "sql-notes", "metrics"]


def test_list_notes(client: TestClient) -> None:
    """GET /v1/notes が3種類の文書を一覧で返すことを確認する。

    Args:
        client: conftest.py の client フィクスチャ（自動で注入される）
    """
    # Act
    response = client.get("/v1/notes")

    # Assert: ステータスコードと、返ってきた文書名の集合
    assert response.status_code == 200
    body = response.json()
    assert [item["doc"] for item in body] == EXPECTED_DOCS

    # 各項目に説明文と URL が入っていること（一覧だけ見て中身が想像できるように）
    for item in body:
        assert item["description"]
        assert item["url"] == f"/v1/notes/{item['doc']}"


# ─── パラメータ化テスト ───────────────────────────────────────────────────
# @pytest.mark.parametrize は「同じテストを引数を変えて繰り返す」仕組み。
# 3つの文書それぞれについて同じ検証をしたいので、3回テストを書く代わりに使う。

@pytest.mark.parametrize("doc", EXPECTED_DOCS)
def test_get_note_returns_markdown(client: TestClient, doc: str) -> None:
    """GET /v1/notes/{doc} が Markdown 本文を返すことを確認する。

    Args:
        client: テスト用 HTTP クライアント
        doc: 取得する文書名（parametrize により3回それぞれの値で実行される）
    """
    # Act
    response = client.get(f"/v1/notes/{doc}")

    # Assert: Markdown として返っており、中身が空でないこと
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# rb2db")


def test_get_note_rejects_unknown_doc(client: TestClient) -> None:
    """定義外の文書名が 422 で拒否されることを確認する。

    文書名は Enum（NoteDoc）で受けているため、FastAPI が定義外の値を弾く。
    これにより「URL から任意のファイル名を渡して別のファイルを読む」
    （パストラバーサル）ができないことも同時に保証される。

    Args:
        client: テスト用 HTTP クライアント
    """
    # Act
    response = client.get("/v1/notes/unknown-doc")

    # Assert
    assert response.status_code == 422


def test_listed_urls_are_fetchable(client: TestClient) -> None:
    """一覧に載っている URL が実際に取得できることを確認する（リンク切れ防止）。

    Args:
        client: テスト用 HTTP クライアント
    """
    # Arrange: まず一覧を取得
    listed = client.get("/v1/notes").json()

    # Act & Assert: 一覧の URL をそのまま叩いて 200 が返ること
    for item in listed:
        assert client.get(item["url"]).status_code == 200


def test_sql_notes_contains_critical_pitfalls(client: TestClient) -> None:
    """sql-notes に最重要の落とし穴が載り続けていることを確認する。

    ドキュメントの中身までテストするのは通常やりすぎだが、ここでは
    「この2点が抜けると利用者が確実に誤った集計をする」ため、
    知識が意図せず削除されるのを防ぐ最低限の歯止めとして検証する。

    Args:
        client: テスト用 HTTP クライアント
    """
    # Act
    text = client.get("/v1/notes/sql-notes").text

    # Assert: ends の NULL 除外と、shot_order の異常値除外
    assert "score_red IS NOT NULL" in text
    assert "shot_order" in text


def test_openapi_description_points_to_notes() -> None:
    """OpenAPI の説明文が /v1/notes への導線を含むことを確認する。

    公開ドキュメント（docs/openapi.json）はこの description から生成されるため、
    ここに導線がないと、API だけを見る利用者が前提知識に辿り着けない。
    """
    # Arrange & Act: アプリの説明文を直接参照する（HTTP 越しでなくてよい）
    from app.main import DESCRIPTION

    # Assert
    assert "/v1/notes" in DESCRIPTION


def test_public_description_excludes_internal_details() -> None:
    """公開される OpenAPI に内部情報が漏れていないことを確認する。

    docs/openapi.json は GitHub Pages で外部に公開される。一方この API 本体は
    研究室内限定公開であり、**実測統計・未修正の不具合・研究室内の集計定義**は
    外部に出す情報ではない。それらは /v1/notes（API 本体からのみ取得可能）に置く。

    ここでは「うっかり description に内部情報を書いてしまう」のを防ぐ歯止めとして、
    代表的な内部情報の断片が OpenAPI 全体に現れないことを検証する。
    """
    import json

    from app.main import app

    # Arrange & Act: OpenAPI 全体を文字列化して走査する
    spec = json.dumps(app.openapi(), ensure_ascii=False)

    # Assert: 実測統計・不具合の詳細・内部リソース名が含まれないこと
    forbidden = [
        "48.4",     # ends の NULL 率（実測統計）
        "63%",      # percent_score の分布（実測統計）
        "1.829",    # ハウス半径（内部ドキュメントの数値）
        "38.405",   # Tee Line 座標（内部ドキュメントの数値）
        "↻",        # lsds.player_name の既知バグの詳細
        "rb2db://",  # MCP リソース名（内部向け）
    ]
    for token in forbidden:
        assert token not in spec, f"内部情報 '{token}' が公開 OpenAPI に含まれている"
