import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# 接続先URLを環境変数から取得
# md   : ミックスダブルス（2人制）のDB
# four : 4人制（Men / Women / Junior）のDB
DATABASE_URL_MD = os.environ["DATABASE_URL_MD"]
DATABASE_URL_FOUR = os.environ["DATABASE_URL_FOUR"]

# DBごとにエンジンを作成
engine_md = create_engine(DATABASE_URL_MD)
engine_four = create_engine(DATABASE_URL_FOUR)

# セッションファクトリ
# autocommit=False : トランザクションを明示的に管理する（読み取り専用APIでも統一）
# autoflush=False  : クエリ前の自動flush を無効化
SessionMd = sessionmaker(autocommit=False, autoflush=False, bind=engine_md)
SessionFour = sessionmaker(autocommit=False, autoflush=False, bind=engine_four)

# ORMモデルの基底クラス（models.py で使用）
Base = declarative_base()


def get_md_db() -> Generator[Session, None, None]:
    """FastAPIの依存性注入（Depends）で使うmdDB用ジェネレータ。

    Yields:
        Session: mdDB用のSQLAlchemyセッション。リクエスト終了時に自動クローズされる。
    """
    db = SessionMd()
    try:
        yield db
    finally:
        db.close()


def get_four_db() -> Generator[Session, None, None]:
    """FastAPIの依存性注入（Depends）で使うfourDB用ジェネレータ。

    Yields:
        Session: fourDB用のSQLAlchemyセッション。リクエスト終了時に自動クローズされる。
    """
    db = SessionFour()
    try:
        yield db
    finally:
        db.close()
