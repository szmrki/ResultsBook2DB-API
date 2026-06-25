"""
scripts/make_test_db.py

通知（notify_update.py）の差分検出・自然言語生成を手軽にテストするための
ダミーSQLite生成スクリプト。

PostgreSQL や update_db.sh を一切経由せず、ローカルのSQLiteファイルだけで
「prev（更新前）」と「new（更新後）」の2ファイルを用意できるようにする。

2つのサブコマンドを持つ:

  shrink  実DB（normal_*.db など）から少数の大会だけを抽出した軽量な
          テスト用ベースDB（test_base.db）を作る。
          stones が100万件超あるため、実DBをそのままコピーすると重い。
          events を起点に外部キー（FK）を辿って関連行だけ抜き出す。

  mutate  ベースDBをコピーし、そこに「変更」を加えた new DB を作る。
          大会追加・カラム追加・テーブル追加・プレイヤー追加などを
          組み合わせて指定でき、差分検出が拾うべきパターンを再現する。

典型的な使い方:

  # 1. 実DBから軽量ベースを作る（events 5件ぶんだけ抽出）
  python scripts/make_test_db.py shrink \
      sqlite/normal_260611.db sqlite/test_base.db --events 5

  # 2. ベースに「大会2件追加 + 謎カラム追加 + テーブル追加」した new を作る
  python scripts/make_test_db.py mutate \
      sqlite/test_base.db sqlite/test_new.db \
      --add-events 2 --add-column shots:foo --add-table experimental

  # 3. 差分通知をSlackに飛ばさず確認する
  PYTHONPATH=. uv run python scripts/notify_update.py \
      --target four \
      --prev-file sqlite/test_base.db \
      --new-file sqlite/test_new.db \
      --dry-run
"""

import argparse
import re
import shutil
import sqlite3

# notify_update.py が差分検出の対象とするテーブル。
# ここに無いテーブル（sqlite_sequence など）は変異・抽出の対象外にする。
TARGET_TABLES = ["events", "games", "ends", "shots", "stones", "lsds"]

# shrink で events を起点に子テーブルを辿るための親子関係。
# (子テーブル, 子側の外部キー列, 親テーブル, 親側の主キー列) のタプル。
# events → games → ends → shots → stones と連鎖し、games → lsds も辿る。
# この順に「親で抽出済みのIDに紐づく子行だけ」を残していく。
FK_CHAIN: list[tuple[str, str, str, str]] = [
    ("games", "event_id", "events", "id"),
    ("ends", "game_id", "games", "id"),
    ("lsds", "game_id", "games", "id"),
    ("shots", "end_id", "ends", "id"),
    ("stones", "shot_id", "shots", "id"),
]


# ─── 共通ユーティリティ ───────────────────────────────────────────────────────


def validate_identifier(name: str) -> str:
    """SQL識別子（テーブル名・カラム名）として安全か検証する。

    テーブル名・カラム名はプレースホルダーで渡せないため、文字列として
    SQLに埋め込む。英数字とアンダースコアのみ許可してSQLインジェクションを防ぐ。

    Args:
        name: 検証する識別子

    Returns:
        str: 検証を通過した識別子（そのまま返す）

    Raises:
        ValueError: 識別子が英字またはアンダースコアで始まる英数字列でない場合
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"不正な識別子: {name!r}")
    return name


def get_tables(conn: sqlite3.Connection) -> list[str]:
    """データベースのテーブル名一覧を取得する。

    Args:
        conn: SQLite接続オブジェクト

    Returns:
        list[str]: テーブル名のリスト（アルファベット順）
    """
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall()]


def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """テーブルのカラム名一覧を取得する。

    Args:
        conn: SQLite接続オブジェクト
        table: テーブル名

    Returns:
        list[str]: カラム名のリスト
    """
    validate_identifier(table)
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


# ─── shrink: 軽量ベースDBの作成 ───────────────────────────────────────────────


def shrink(src_file: str, dst_file: str, event_limit: int) -> None:
    """実DBから少数の大会ぶんだけを抽出した軽量ベースDBを作る。

    events を id の昇順に event_limit 件だけ残し、そこから外部キーを辿って
    関連する games / ends / shots / stones / lsds の行だけを残す。
    対象外のテーブル（sqlite_sequence など）はそのままコピーされた状態で残る。

    実装方針:
      1. src を dst にまるごとコピー（スキーマ・データを丸ごと複製）
      2. dst 側で events を上位 event_limit 件以外 DELETE
      3. FK_CHAIN を親→子の順に辿り、親に残っていない行を子から DELETE
      4. VACUUM でファイルサイズを実際に縮める

    Args:
        src_file: コピー元の実SQLiteファイルパス
        dst_file: 出力する軽量ベースDBのパス
        event_limit: 残す events の件数

    Returns:
        None
    """
    # 1. まるごとコピー（DROP/CREATE を書かずに済むのでスキーマ完全一致が保証される）
    shutil.copyfile(src_file, dst_file)
    conn = sqlite3.connect(dst_file)
    try:
        existing = set(get_tables(conn))

        # 2. events を上位 event_limit 件に絞る
        #    「残すIDの集合」をサブクエリで作り、それ以外を削除する
        if "events" in existing:
            conn.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY id LIMIT ?)",
                (event_limit,),
            )

        # 3. 親→子の順に「親に残っていない行」を子から削除する
        #    FK_CHAIN は親が先に処理される順に並んでいるので、上から辿れば
        #    親の絞り込みが子に正しく伝播する
        for child, fk_col, parent, parent_pk in FK_CHAIN:
            if child not in existing or parent not in existing:
                continue
            validate_identifier(child)
            validate_identifier(fk_col)
            validate_identifier(parent)
            validate_identifier(parent_pk)
            # 子テーブルのうち、親に残っているIDを参照していない行を削除
            conn.execute(
                f"DELETE FROM {child} WHERE {fk_col} NOT IN "  # noqa: S608
                f"(SELECT {parent_pk} FROM {parent})"
            )

        conn.commit()
        # 4. VACUUM で削除済み領域を回収して実ファイルを小さくする
        #    （DELETE しただけではファイルサイズは縮まないため）
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    # 件数サマリを表示して結果を確認できるようにする
    print(f"軽量ベースDBを作成しました: {dst_file}")
    _print_summary(dst_file)


# ─── mutate: 差分を加えた new DBの作成 ────────────────────────────────────────


def add_events(conn: sqlite3.Connection, count: int) -> None:
    """ダミーの大会（events行）を追加する。

    新規大会名は notify_update.py の added_names 検出で拾われる。

    Args:
        conn: SQLite接続オブジェクト
        count: 追加する大会数

    Returns:
        None
    """
    cols = get_columns(conn, "events")
    for i in range(count):
        # name 以外は最低限の値で埋める。テスト用なので内容は何でもよい。
        name = f"テストカップ{i + 1}"
        # events のカラム構成（id, name, year, category）に合わせて値を作る。
        # id は省略すると自動採番される想定だが、明示せず name/year/category だけ入れる。
        values: dict[str, object] = {"name": name, "year": 2026, "category": "test"}
        # 実際に存在するカラムだけINSERT対象にする（スキーマ差異への保険）
        use_cols = [c for c in cols if c in values]
        placeholders = ", ".join("?" for _ in use_cols)
        col_list = ", ".join(use_cols)
        conn.execute(
            f"INSERT INTO events ({col_list}) VALUES ({placeholders})",  # noqa: S608
            tuple(values[c] for c in use_cols),
        )
    print(f"  events に {count} 件のダミー大会を追加")


def add_players(conn: sqlite3.Connection, count: int) -> None:
    """ダミーのショット（shots行）を追加し、新規プレイヤー名を発生させる。

    shots.player_name の新規値は notify_update.py の new_players 検出で拾われる。
    外部キー（end_id）には既存の end をひとつ流用する。

    Args:
        conn: SQLite接続オブジェクト
        count: 追加するショット数（= 新規プレイヤー数）

    Returns:
        None
    """
    cols = get_columns(conn, "shots")
    # 既存の end をひとつ取得してFKに使う（無ければ何もしない）
    row = conn.execute("SELECT id FROM ends LIMIT 1").fetchone()
    if row is None:
        print("  ends が空のため shots 追加をスキップ")
        return
    end_id = row[0]
    for i in range(count):
        values: dict[str, object] = {
            "end_id": end_id,
            "number": 1,
            "color": "red",
            "team": "テストチーム",
            "player_name": f"テスト選手{i + 1}",
            "type": "draw",
            "turn": "in",
            "percent_score": 100,
        }
        use_cols = [c for c in cols if c in values]
        placeholders = ", ".join("?" for _ in use_cols)
        col_list = ", ".join(use_cols)
        conn.execute(
            f"INSERT INTO shots ({col_list}) VALUES ({placeholders})",  # noqa: S608
            tuple(values[c] for c in use_cols),
        )
    print(f"  shots に {count} 件のダミーショット（新規プレイヤー）を追加")


def add_column(conn: sqlite3.Connection, spec: str) -> None:
    """既存テーブルに新しいカラムを追加する（スキーマ差分のテスト用）。

    Args:
        conn: SQLite接続オブジェクト
        spec: "テーブル名:カラム名" 形式の文字列（例 "shots:foo"）

    Returns:
        None

    Raises:
        ValueError: spec の形式が不正な場合、または対象テーブルが存在しない場合
    """
    if ":" not in spec:
        raise ValueError(f"--add-column は TABLE:COLUMN 形式で指定してください: {spec!r}")
    table, column = spec.split(":", 1)
    validate_identifier(table)
    validate_identifier(column)
    if table not in get_tables(conn):
        raise ValueError(f"存在しないテーブルです: {table!r}")
    # ALTER TABLE ... ADD COLUMN で空のカラムを追加する
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")  # noqa: S608
    print(f"  {table} に謎カラム {column!r} を追加")


def add_table(conn: sqlite3.Connection, name: str) -> None:
    """新しいテーブルを追加する（テーブル追加差分のテスト用）。

    Args:
        conn: SQLite接続オブジェクト
        name: 追加するテーブル名

    Returns:
        None

    Raises:
        ValueError: テーブル名が不正、または既に存在する場合
    """
    validate_identifier(name)
    if name in get_tables(conn):
        raise ValueError(f"既に存在するテーブルです: {name!r}")
    # 最小限のスキーマで作成（中身は問わない、存在差分だけ作りたいので）
    conn.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, value TEXT)")  # noqa: S608
    print(f"  テーブル {name!r} を追加")


def mutate(args: argparse.Namespace) -> None:
    """ベースDBをコピーして指定された変異を加えた new DB を作る。

    Args:
        args: コマンドライン引数（base_file, dst_file と各変異オプションを含む）

    Returns:
        None
    """
    # ベースをそのままコピーしてから差分を加える
    shutil.copyfile(args.base_file, args.dst_file)
    conn = sqlite3.connect(args.dst_file)
    try:
        print(f"変異を適用中: {args.dst_file}")
        # 指定された変異を順に適用する（複数同時指定可）
        if args.add_table:
            for name in args.add_table:
                add_table(conn, name)
        if args.add_column:
            for spec in args.add_column:
                add_column(conn, spec)
        if args.add_events:
            add_events(conn, args.add_events)
        if args.add_players:
            add_players(conn, args.add_players)
        conn.commit()
    finally:
        conn.close()

    print(f"new DBを作成しました: {args.dst_file}")
    _print_summary(args.dst_file)


# ─── サマリ表示 ───────────────────────────────────────────────────────────────


def _print_summary(db_file: str) -> None:
    """DBのテーブル別件数サマリを標準出力に表示する。

    Args:
        db_file: 対象SQLiteファイルのパス

    Returns:
        None
    """
    conn = sqlite3.connect(db_file)
    try:
        print("  --- テーブル件数 ---")
        for table in get_tables(conn):
            # サマリ表示なのでホワイトリスト外（sqlite_sequence等）も含めて表示する
            validate_identifier(table)
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            cols = get_columns(conn, table)
            print(f"  {table}: {cnt:,} 件 / カラム {cols}")
    finally:
        conn.close()


# ─── エントリーポイント ───────────────────────────────────────────────────────


def main() -> None:
    """サブコマンドを解析して shrink または mutate を実行する。"""
    parser = argparse.ArgumentParser(
        description="通知テスト用のダミーSQLiteを生成するスクリプト"
    )
    # サブコマンド（shrink / mutate）を定義する
    sub = parser.add_subparsers(dest="command", required=True)

    # ── shrink サブコマンド ─────────────────────────────────────────
    p_shrink = sub.add_parser("shrink", help="実DBから軽量ベースDBを作る")
    p_shrink.add_argument("src_file", help="コピー元の実SQLiteファイル")
    p_shrink.add_argument("dst_file", help="出力する軽量ベースDBのパス")
    p_shrink.add_argument(
        "--events", type=int, default=5,
        help="残す大会（events）の件数（デフォルト5）",
    )

    # ── mutate サブコマンド ─────────────────────────────────────────
    p_mutate = sub.add_parser("mutate", help="ベースDBに差分を加えた new DBを作る")
    p_mutate.add_argument("base_file", help="ベースDB（prev側）のパス")
    p_mutate.add_argument("dst_file", help="出力する new DBのパス")
    p_mutate.add_argument(
        "--add-events", type=int, default=0,
        help="追加するダミー大会の件数",
    )
    p_mutate.add_argument(
        "--add-players", type=int, default=0,
        help="追加するダミーショット（新規プレイヤー）の件数",
    )
    p_mutate.add_argument(
        "--add-column", action="append", default=[], metavar="TABLE:COLUMN",
        help="追加する謎カラム（複数指定可）例: --add-column shots:foo",
    )
    p_mutate.add_argument(
        "--add-table", action="append", default=[], metavar="NAME",
        help="追加するテーブル名（複数指定可）例: --add-table experimental",
    )

    args = parser.parse_args()

    if args.command == "shrink":
        shrink(args.src_file, args.dst_file, args.events)
    elif args.command == "mutate":
        mutate(args)


if __name__ == "__main__":
    main()
