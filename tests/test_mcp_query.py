"""app/mcp/query.py と、MCP サーバーの大量データ誘導まわりのテスト。

- _to_jsonable: DB 由来の Decimal（AVG などの集計結果）が float に変換されること
- run_query: 行数上限を超えたときだけ hint（REST API への誘導）が付くこと
  （DB は SQLite に差し替えて実行する）
- instructions: 大量データ取得の経路（REST API）が案内されていること
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine

from app.mcp import query as query_module
from app.mcp import server
from app.mcp.config import API_URL_PLACEHOLDER
from app.mcp.query import _to_jsonable
from app.pagination import MAX_LIMIT


def test_basic_types_pass_through() -> None:
    """None・bool・int・float・str はそのまま返る。"""
    assert _to_jsonable(None) is None
    assert _to_jsonable(True) is True
    assert _to_jsonable(42) == 42
    assert _to_jsonable(3.14) == 3.14
    assert _to_jsonable("red") == "red"


def test_decimal_is_converted_to_float() -> None:
    """PostgreSQL の集計が返す Decimal は float に変換される。"""
    result = _to_jsonable(Decimal("0.7141202586622912"))
    assert isinstance(result, float)
    assert result == 0.7141202586622912


def test_non_json_types_fall_back_to_str() -> None:
    """date/datetime などは文字列表現にフォールバックする。"""
    d = datetime.date(2026, 7, 13)
    assert _to_jsonable(d) == "2026-07-13"


# ─── truncated 時の hint（大量データは REST API へ誘導する） ──────────────────
# run_query の結果は AI のコンテキストを経由するため、大量の生データ取得には向かない。
# 上限にぶつかった瞬間に「集計するか、REST API でファイルに保存するか」を AI に示すのが
# hint の役目。ここでは「切り落としたときだけ付く」ことを確かめる。
#
# run_query 本体は本番では PostgreSQL の read-only エンジンを使うが、
# テストでは monkeypatch で SQLite のインメモリ DB に差し替えて実行する。
# （monkeypatch は pytest 組み込みのフィクスチャで、テスト中だけ属性を置き換え、
#   終了後に自動で元へ戻してくれる）


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Engine:
    """run_query が使うエンジンを SQLite に差し替え、行数上限を 3 行に下げる。

    Args:
        monkeypatch: pytest 組み込みの属性差し替え用フィクスチャ。

    Returns:
        差し替え先の SQLite エンジン。
    """
    engine = create_engine("sqlite:///:memory:")
    # query モジュールが import 済みの名前を差し替える（config 側ではなく使う側を直す）
    monkeypatch.setattr(query_module, "get_engine", lambda db: engine)
    monkeypatch.setattr(query_module, "MAX_ROWS", 3)
    return engine


# 1〜n の連番を返す SQL（WITH RECURSIVE で行を作るので、テーブルを用意しなくてよい）
_SERIES_SQL = (
    "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t WHERE n < {n}) "
    "SELECT n FROM t"
)


def test_hint_added_when_truncated(sqlite_engine: Engine) -> None:
    """上限（3 行）を超えたら truncated=True になり、REST API へ誘導する hint が付く。

    Args:
        sqlite_engine: SQLite に差し替えたエンジン（フィクスチャ）。
    """
    result = query_module.run_query(_SERIES_SQL.format(n=5), "md")

    assert result["truncated"] is True
    assert result["row_count"] == 3
    # 中身はサーバーの設定値で組み立てた TRUNCATION_HINT（文面は下の build 系のテストで確かめる）
    assert result["hint"] == query_module.TRUNCATION_HINT


def test_no_hint_when_not_truncated(sqlite_engine: Engine) -> None:
    """上限ちょうど（3 行）なら切り落とさず、hint も付かない（通常の応答の形を変えない）。

    Args:
        sqlite_engine: SQLite に差し替えたエンジン（フィクスチャ）。
    """
    result = query_module.run_query(_SERIES_SQL.format(n=3), "md")

    assert result["truncated"] is False
    assert result["row_count"] == 3
    assert "hint" not in result


# ─── instructions と hint の文面（URL あり / なし） ─────────────────────────
# 本番の URL はリポジトリに書かず、サーバーの .env にだけ置く。
# そのため「URL が設定されている場合」と「未設定の場合」の両方で、文面が正しく
# 組み立てられることを確かめる。テスト用の URL には予約済みの example.com を使う。

_TEST_API_URL = "https://api.example.com"


def test_instructions_with_api_url() -> None:
    """URL が設定されていれば、instructions に API の URL と手順が載る。"""
    text = server.build_instructions(_TEST_API_URL)

    assert f"REST API（{_TEST_API_URL}）" in text
    assert f"{_TEST_API_URL}/openapi.json" in text
    assert "CF_ACCESS_CLIENT_ID" in text
    assert "CF_ACCESS_CLIENT_SECRET" in text
    assert f"{MAX_LIMIT:,}" in text
    # URL があるときは目印も「ユーザーに確認」の一文も出ない
    assert API_URL_PLACEHOLDER not in text
    assert "ユーザーに確認する" not in text


def test_instructions_without_api_url() -> None:
    """URL が未設定なら、URL の代わりに目印を置き、ユーザーに確認するよう案内する。"""
    text = server.build_instructions("")

    assert f"REST API（{API_URL_PLACEHOLDER}）" in text
    assert "API の URL はユーザーに確認する" in text
    # 未設定でも、認証やページングの手順は変わらず載っていること
    assert "CF_ACCESS_CLIENT_ID" in text
    assert f"{MAX_LIMIT:,}" in text


def test_truncation_hint_with_and_without_api_url() -> None:
    """hint も同様に、URL あり / なしで文面が切り替わる。"""
    with_url = query_module.build_truncation_hint(_TEST_API_URL)
    assert _TEST_API_URL in with_url
    assert "CF_ACCESS_CLIENT_ID" in with_url
    assert "ユーザーに確認" not in with_url

    without_url = query_module.build_truncation_hint("")
    assert API_URL_PLACEHOLDER in without_url
    assert "ユーザーに確認" in without_url
