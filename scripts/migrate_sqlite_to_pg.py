"""
SQLite → PostgreSQL データ移行スクリプト。

SQLite のデータベースファイルから全データを読み出し、
PostgreSQL に全削除→再投入（full refresh）する。

何度でも実行可能（冪等）。テーブルを DROP して再作成するため、
スキーマ変更（カラム追加など）にも対応する。

使い方:
    # md DB の移行
    python scripts/migrate_sqlite_to_pg.py memo/md_260514.db \
      --pg-url postgresql://curling:password@localhost:5432/rb2db_md

    # four DB の移行
    python scripts/migrate_sqlite_to_pg.py memo/normal_260502.db \
      --pg-url postgresql://curling:password@localhost:5432/rb2db_four
"""

import argparse
import sqlite3
import sys
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# database.py が import 時に環境変数（DATABASE_URL_MD 等）を読むため、
# app をインポートする前に .env を読み込む必要がある
load_dotenv()

# models.py で定義した Base（全テーブル情報を持つ）をインポート
# Base.metadata にテーブル定義が格納されている
from app.database import Base  # noqa: E402
from app.models import End, Event, Game, Lsd, Shot, Stone  # noqa: E402

# ─── 設定 ──────────────────────────────────────────────────────────────────────

# バルクインサートのバッチサイズ
# 一度に INSERT する件数。大きすぎるとメモリを消費し、小さすぎると遅い。
# stones（100万件超）を考慮して 5000 件に設定。
BATCH_SIZE = 5000

# テーブル情報の定義
# 投入順序は外部キー制約に従う（親テーブルから順に）
# - sqlite_table: SQLite 側のテーブル名
# - model: SQLAlchemy モデルクラス
# - columns: 移行対象のカラム名リスト（SQLite のカラム名と一致させる）
TABLES = [
    {
        "sqlite_table": "events",
        "model": Event,
        "columns": ["id", "name", "year", "category"],
    },
    {
        "sqlite_table": "games",
        "model": Game,
        "columns": [
            "id", "event_id", "page",
            "team_red", "team_yellow",
            "final_score_red", "final_score_yellow",
        ],
    },
    {
        "sqlite_table": "ends",
        "model": End,
        "columns": [
            "id", "game_id", "page", "number",
            "color_hammer", "score_red", "score_yellow", "is_power_play",
        ],
    },
    {
        "sqlite_table": "shots",
        "model": Shot,
        "columns": [
            "id", "end_id", "number", "color",
            "team", "player_name", "type", "turn", "percent_score",
        ],
    },
    {
        "sqlite_table": "stones",
        "model": Stone,
        "columns": [
            "id", "shot_id", "color", "x", "y",
            "distance_from_center", "inhouse", "insheet",
        ],
    },
    {
        "sqlite_table": "lsds",
        "model": Lsd,
        "columns": ["id", "game_id", "team", "player_name", "distance_cm"],
    },
]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。

    Returns:
        argparse.Namespace: sqlite_path と pg_url を含む引数オブジェクト
    """
    parser = argparse.ArgumentParser(
        description="SQLite → PostgreSQL データ移行スクリプト",
    )
    # 位置引数: SQLite ファイルのパス
    parser.add_argument(
        "sqlite_path",
        help="移行元の SQLite ファイルパス（例: memo/md_260514.db）",
    )
    # オプション引数: PostgreSQL の接続URL
    parser.add_argument(
        "--pg-url",
        required=True,
        help="PostgreSQL の接続URL（例: postgresql://user:pass@localhost:5432/rb2db_md）",
    )
    return parser.parse_args()


def get_sqlite_columns(sqlite_conn: sqlite3.Connection, table_name: str) -> list[str]:
    """SQLite テーブルに存在するカラム名の一覧を取得する。

    PRAGMA table_info() は SQLite のメタ情報を返すコマンド。
    各行の2番目（index=1）がカラム名。

    Args:
        sqlite_conn: SQLite のコネクション
        table_name: テーブル名

    Returns:
        list[str]: カラム名のリスト
    """
    cursor = sqlite_conn.execute(f"PRAGMA table_info({table_name})")  # noqa: S608
    return [row[1] for row in cursor.fetchall()]


def get_sqlite_count(sqlite_conn: sqlite3.Connection, table_name: str) -> int:
    """SQLite テーブルのレコード件数を取得する。

    Args:
        sqlite_conn: SQLite のコネクション
        table_name: テーブル名

    Returns:
        int: レコード件数
    """
    cursor = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table_name}")  # noqa: S608
    return cursor.fetchone()[0]


def get_sqlite_rows(
    sqlite_conn: sqlite3.Connection,
    table_name: str,
    columns: list[str],
) -> list[sqlite3.Row]:
    """SQLite テーブルから全行を取得する。

    Args:
        sqlite_conn: SQLite のコネクション
        table_name: テーブル名
        columns: 取得するカラム名のリスト

    Returns:
        list[sqlite3.Row]: 全行のリスト（辞書形式でアクセス可能）
    """
    # row_factory を設定すると、row["id"] のように辞書風にアクセスできる
    sqlite_conn.row_factory = sqlite3.Row
    cols = ", ".join(columns)
    cursor = sqlite_conn.execute(f"SELECT {cols} FROM {table_name}")  # noqa: S608
    return cursor.fetchall()


def reset_sequence(pg_session: sessionmaker, table_name: str) -> None:
    """PostgreSQL の SERIAL シーケンスを最大 ID に合わせてリセットする。

    SQLite から明示的に ID を指定して INSERT するため、
    PostgreSQL の auto increment 用シーケンスがずれる。
    これをリセットしないと、次に INSERT したとき ID が衝突する可能性がある。

    Args:
        pg_session: PostgreSQL のセッション
        table_name: テーブル名
    """
    # setval(): シーケンスの現在値を設定する PostgreSQL 関数
    # pg_get_serial_sequence(): テーブルの id カラムに紐づくシーケンス名を取得
    # COALESCE(): MAX(id) が NULL（テーブルが空）の場合は 1 を返す
    pg_session.execute(text(f"""
        SELECT setval(
            pg_get_serial_sequence('{table_name}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table_name}), 1)
        )
    """))


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_session: sessionmaker,
    table_info: dict,
) -> None:
    """1テーブル分のデータを SQLite → PostgreSQL に移行する。

    Args:
        sqlite_conn: SQLite のコネクション
        pg_session: PostgreSQL のセッション
        table_info: テーブル情報（sqlite_table, model, columns）
    """
    table_name = table_info["sqlite_table"]
    model = table_info["model"]
    columns = table_info["columns"]

    # SQLite に実際に存在するカラムだけに絞る
    # 例: four DB の ends には is_power_play がないので除外される
    sqlite_columns = get_sqlite_columns(sqlite_conn, table_name)
    columns = [c for c in columns if c in sqlite_columns]

    # SQLite から全行取得
    rows = get_sqlite_rows(sqlite_conn, table_name, columns)
    total = len(rows)
    print(f"  {table_name}: {total} 件を移行中...", end="", flush=True)

    start = time.time()

    # バッチに分割してバルクインサート
    # rows[i:i+BATCH_SIZE] でスライスして、BATCH_SIZE 件ずつ INSERT する
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        # dict(row) で sqlite3.Row を辞書に変換し、モデルのコンストラクタに渡す
        # 例: Event(id=1, name="WMDCC2023", year=2023, category="MD")
        pg_session.bulk_save_objects(
            [model(**dict(row)) for row in batch]
        )
        # バッチごとにコミットしてメモリを解放
        pg_session.commit()

    # シーケンスをリセット
    reset_sequence(pg_session, table_name)
    pg_session.commit()

    elapsed = time.time() - start
    print(f" 完了 ({elapsed:.1f}秒)")


def verify_counts(
    sqlite_conn: sqlite3.Connection,
    pg_session: sessionmaker,
) -> bool:
    """SQLite と PostgreSQL のレコード件数が一致するか検証する。

    Args:
        sqlite_conn: SQLite のコネクション
        pg_session: PostgreSQL のセッション

    Returns:
        bool: 全テーブルの件数が一致すれば True
    """
    print("\n--- 件数チェック ---")
    all_ok = True

    for table_info in TABLES:
        table_name = table_info["sqlite_table"]
        model = table_info["model"]

        sqlite_count = get_sqlite_count(sqlite_conn, table_name)
        pg_count = pg_session.query(model).count()

        # ✓ か ✗ で結果を表示
        if sqlite_count == pg_count:
            status = "OK"
        else:
            status = "NG"
            all_ok = False

        print(f"  {table_name}: SQLite={sqlite_count}, PG={pg_count} [{status}]")

    return all_ok


def main() -> None:
    """メイン処理。SQLite → PostgreSQL のデータ移行を実行する。"""
    args = parse_args()

    # ─── SQLite 接続 ──────────────────────────────────────────────────────
    print(f"SQLite: {args.sqlite_path}")
    sqlite_conn = sqlite3.connect(args.sqlite_path)

    # SQLite 側のテーブル件数を表示
    print("\n--- SQLite テーブル件数 ---")
    for table_info in TABLES:
        table_name = table_info["sqlite_table"]
        try:
            count = get_sqlite_count(sqlite_conn, table_name)
            print(f"  {table_name}: {count} 件")
        except sqlite3.OperationalError:
            # テーブルが存在しない場合（例: is_power_play がない four 側の ends）
            print(f"  {table_name}: テーブルなし（スキップ）")

    # ─── PostgreSQL 接続 ──────────────────────────────────────────────────
    print(f"\nPostgreSQL: {args.pg_url}")
    pg_engine = create_engine(args.pg_url)
    PgSession = sessionmaker(bind=pg_engine)
    pg_session = PgSession()

    # ─── テーブル再作成 ────────────────────────────────────────────────────
    # DROP ALL → CREATE ALL でスキーマ変更にも対応
    print("\nテーブルを再作成中...")
    Base.metadata.drop_all(pg_engine)    # 全テーブル削除
    Base.metadata.create_all(pg_engine)  # models.py の定義から全テーブル作成
    print("  完了")

    # ─── データ移行 ────────────────────────────────────────────────────────
    print("\nデータ移行中...")
    total_start = time.time()

    for table_info in TABLES:
        migrate_table(sqlite_conn, pg_session, table_info)

    total_elapsed = time.time() - total_start
    print(f"\n全テーブル移行完了 (合計 {total_elapsed:.1f}秒)")

    # ─── 件数チェック ──────────────────────────────────────────────────────
    all_ok = verify_counts(sqlite_conn, pg_session)

    # ─── クリーンアップ ───────────────────────────────────────────────────
    pg_session.close()
    sqlite_conn.close()

    if all_ok:
        print("\n移行成功")
    else:
        print("\n移行失敗: 件数が一致しないテーブルがあります")
        sys.exit(1)


if __name__ == "__main__":
    main()
