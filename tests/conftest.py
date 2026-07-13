"""
pytest 共通設定ファイル。

conftest.py の役割:
  - テスト全体で使う「フィクスチャ（fixture）」を定義する
  - テスト用の DB（SQLite インメモリ）のセットアップをする
  - FastAPI の依存性注入（Depends）をテスト用に差し替える

【なぜ本番の PostgreSQL を使わないのか】
  CI（GitHub Actions）で本番の DB に繋ぐのは難しい（接続情報の管理、DB の起動など）。
  代わりに SQLite のインメモリ DB を使う:
    - Python 標準ライブラリなのでインストール不要
    - メモリ上で動くのでテスト後に自動消滅（後片付け不要）
    - テストが速い

【重要: import の順番について】
  app/database.py は、モジュールが読み込まれた瞬間に
  os.environ["DATABASE_URL_MD"] を読み取って DB エンジンを作る。
  そのため、app を import する *前に* 環境変数を設定しておく必要がある。
  （設定後に load_dotenv() が呼ばれても、既存の環境変数は上書きされない）
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ─── ① 環境変数の設定（app の import より先に書く） ────────────────────────
# app/database.py が読み込まれたとき、この値を参照してエンジンを作る。
# テストでは本番 DB への接続は不要なので SQLite を指定する。
os.environ["DATABASE_URL_MD"] = "sqlite:///:memory:"
os.environ["DATABASE_URL_FOUR"] = "sqlite:///:memory:"

# MCP サーバー（app/mcp）は import 時に read-only 接続URLを要求する。
# テストでは実接続しない純粋ロジック（sql_guard / _to_jsonable）のみ検証するため、
# import を通すためのダミーとして SQLite を指定しておく。
os.environ["DATABASE_URL_MD_RO"] = "sqlite:///:memory:"
os.environ["DATABASE_URL_FOUR_RO"] = "sqlite:///:memory:"

# ─── ② app と DB 関連クラスを import ────────────────────────────────────────
# ここで初めて app を import する。
# この時点で app/database.py の engine_md / engine_four は SQLite で作られる。
from app.database import Base, get_four_db, get_md_db  # noqa: E402
from app.main import app  # noqa: E402

# ─── ③ テスト用エンジンの作成 ─────────────────────────────────────────────
# app/database.py でも SQLite エンジンが作られるが、テストではこちらを使う。
# テスト用エンジンは依存性注入の差し替えで FastAPI に渡す（後述）。
#
# StaticPool とは:
#   SQLite のインメモリ DB は通常「接続ごとに別のDB」として扱われる。
#   つまり session1 で INSERT したデータが session2 から見えない。
#   StaticPool を使うと「全接続が同じインメモリ DB を共有」するようになる。
#   テスト中に複数のセッションが同じデータを見られるようにするために必須。
#
# check_same_thread=False:
#   SQLite はデフォルトで「作成したスレッドからしか使えない」という制限がある。
#   pytest は複数スレッドを使うことがあるため、この制限を解除する。
SQLITE_OPTIONS = {
    "connect_args": {"check_same_thread": False},
    "poolclass": StaticPool,
}
engine_md_test = create_engine("sqlite:///:memory:", **SQLITE_OPTIONS)
engine_four_test = create_engine("sqlite:///:memory:", **SQLITE_OPTIONS)

# ─── ④ テスト用セッションファクトリ ──────────────────────────────────────
# sessionmaker は「DB セッションを作る工場」。
# bind= でどのエンジン（≒どの DB）に接続するかを指定する。
SessionMdTest = sessionmaker(bind=engine_md_test)
SessionFourTest = sessionmaker(bind=engine_four_test)


# ─── ⑤ 依存性注入の差し替え関数 ──────────────────────────────────────────
# FastAPI の依存性注入（Depends）は「テスト時だけ別の関数に差し替える」ことができる。
# これを「オーバーライド」と呼ぶ。
# 本番: get_md_db → PostgreSQL の SessionMd を yield
# テスト: override_get_md_db → SQLite の SessionMdTest を yield
def override_get_md_db():
    """テスト用の md DB セッションを提供するジェネレータ。"""
    db = SessionMdTest()
    try:
        yield db
    finally:
        db.close()


def override_get_four_db():
    """テスト用の four DB セッションを提供するジェネレータ。"""
    db = SessionFourTest()
    try:
        yield db
    finally:
        db.close()


# ─── ⑥ FastAPI のオーバーライドを登録 ─────────────────────────────────────
# app.dependency_overrides は辞書形式で、
# 「元の依存関数 → 置き換える関数」 を登録する。
# この1行だけで、テスト中の全エンドポイントが SQLite を使うようになる。
app.dependency_overrides[get_md_db] = override_get_md_db
app.dependency_overrides[get_four_db] = override_get_four_db


# ─── ⑦ フィクスチャ定義 ─────────────────────────────────────────────────
#
# フィクスチャとは:
#   テスト関数に「事前準備・後片付け」を自動でやってくれる仕組み。
#   @pytest.fixture で定義し、テスト関数の引数に書くだけで自動的に実行される。
#
# autouse=True:
#   全テストに自動で適用する。引数に書かなくても常に実行される。
#   ここでは各テストの前後にテーブルを初期化するために使う。

@pytest.fixture(autouse=True)
def reset_db():
    """各テストの前にテーブルを初期化する。

    - drop_all: 全テーブルを削除
    - create_all: 全テーブルを再作成
    これにより、あるテストで INSERT したデータが次のテストに影響しない。

    yield の前: テスト実行前の処理（セットアップ）
    yield の後: テスト実行後の処理（ティアダウン）
    """
    Base.metadata.drop_all(bind=engine_md_test)
    Base.metadata.drop_all(bind=engine_four_test)
    Base.metadata.create_all(bind=engine_md_test)
    Base.metadata.create_all(bind=engine_four_test)
    yield  # ← ここでテスト本体が実行される
    # テスト後の後片付け（今回は reset_db の次の呼び出しで drop_all するので省略可）


@pytest.fixture
def client() -> TestClient:
    """テスト用 HTTP クライアントを提供するフィクスチャ。

    TestClient とは:
      実際にサーバーを起動せずに、HTTP リクエストをシミュレートするツール。
      テスト中は「実際に localhost に接続する」のではなく、
      FastAPI アプリに直接リクエストを投げる。

    Returns:
        TestClient: テスト用の HTTP クライアント
    """
    return TestClient(app)


@pytest.fixture
def md_db():
    """テストデータを直接 DB に INSERT するためのセッションを提供するフィクスチャ。

    テストの「準備」として DB にデータを入れたい場合に使う。
    例: 特定の大会データを INSERT しておいてから、GET /events を呼ぶ

    Yields:
        Session: md DB 用の SQLAlchemy セッション
    """
    db = SessionMdTest()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def four_db():
    """テストデータを直接 DB に INSERT するためのセッションを提供するフィクスチャ（four DB 用）。

    Yields:
        Session: four DB 用の SQLAlchemy セッション
    """
    db = SessionFourTest()
    try:
        yield db
    finally:
        db.close()
