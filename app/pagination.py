"""ページネーション共通定数とクエリパラメータ定義。

各ルーターで `limit` / `offset` のクエリパラメータをべた書き（`Query(default=50, ge=1, le=1000)`）
していたものを、この1か所に集約する。上限値を変えたいときはここだけを直せば全エンドポイントに
反映される（以前は各ルーターに散っていて変更漏れの温床だった）。

MAX_LIMIT の根拠:
  分析用途で「1大会（event）単位の全 stones を1リクエストで取得する」ことを設計目標にした。
  実測（2026-07-13）では event 単位の stones 件数は最大 66,980 件（md）/ 53,094 件（four）。
  この最大値に十分な余裕を持たせて 100,000 に設定している。これにより:
    - どの大会の stones も 1 リクエストで取得できる（従来は limit 1000 で数十リクエスト必要だった）
    - stones 全件（約115万件）でも 12 リクエスト程度で取得でき、レート制限に事実上当たらない
  詳細な経緯は memo/api_design.md / issue #13 を参照。
"""

from fastapi import Query

# 一覧取得のデフォルト件数（クライアントが limit を指定しなかったときの値）
DEFAULT_LIMIT = 50

# 一覧取得で許可する最大件数（これを超える limit は 422 で拒否される）
MAX_LIMIT = 100_000


def limit_query() -> int:
    """一覧取得の `limit` クエリパラメータ定義を返す。

    各ルーターの引数で `limit: int = limit_query()` のように使う。
    デフォルト値・範囲制限（1 以上 MAX_LIMIT 以下）を共通化する。

    Returns:
        FastAPI の Query オブジェクト（型上は int として扱われる）。
    """
    # ge=1: 1 以上（0 件取得は無意味なので下限を 1 にする）
    # le=MAX_LIMIT: MAX_LIMIT 以下（上限。超えると 422 バリデーションエラー）
    return Query(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"取得件数の上限（1〜{MAX_LIMIT}）",
    )


def offset_query() -> int:
    """一覧取得の `offset` クエリパラメータ定義を返す。

    各ルーターの引数で `offset: int = offset_query()` のように使う。

    Returns:
        FastAPI の Query オブジェクト（型上は int として扱われる）。
    """
    # ge=0: 0 以上（先頭からの取得開始位置）
    return Query(default=0, ge=0, description="取得開始位置（0以上）")
