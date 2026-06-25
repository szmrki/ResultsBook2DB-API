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
          大会追加（試合・エンド・ショット・ストーンも連動）・カラム追加・
          テーブル追加を組み合わせて指定でき、差分検出が拾うべきパターンを再現する。

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

# 1大会（events 1件）を追加したときに生成する子レコードの規模。
# 実際の更新（大会が増えれば試合・エンド・ショット・ストーンも増える）を
# 模すための定数。値を変えればテストの規模を調整できる。
ENDS_PER_GAME = 10          # 1試合あたりのエンド数
SHOTS_PER_END = 16         # 1エンドあたりのショット数（4人×2投×赤黄）
STONES_PER_SHOT = 2        # 1ショットあたりのストーン配置数（適当）


def _insert_row(conn: sqlite3.Connection, table: str, values: dict[str, object]) -> int:
    """テーブルに1行INSERTし、採番された rowid を返す。

    実在するカラムだけをINSERT対象にする（スキーマ差異への保険）。
    INTEGER PRIMARY KEY を持つテーブルでは lastrowid が主キー id になる。

    Args:
        conn: SQLite接続オブジェクト
        table: INSERT先テーブル名
        values: カラム名→値の辞書（存在しないカラムは無視される）

    Returns:
        int: INSERTした行の rowid（= id）
    """
    validate_identifier(table)
    cols = get_columns(conn, table)
    # values のうち、実際に存在するカラムだけINSERTする
    use_cols = [c for c in cols if c in values]
    placeholders = ", ".join("?" for _ in use_cols)
    col_list = ", ".join(use_cols)
    cursor = conn.execute(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",  # noqa: S608
        tuple(values[c] for c in use_cols),
    )
    # lastrowid は直前のINSERTで採番された rowid
    return cursor.lastrowid


def add_events(conn: sqlite3.Connection, count: int) -> None:
    """ダミーの大会を、関連する試合・エンド・ショット・ストーンごと追加する。

    1大会につき以下を生成し、現実の更新（大会追加に伴う子レコード増加）を模す:
      - events  1件
      - games   1件（その大会の試合）
      - ends    ENDS_PER_GAME 件（1試合のエンド）
      - shots   各エンド SHOTS_PER_END 件
      - stones  各ショット STONES_PER_SHOT 件

    新規大会名は notify_update.py の added_names 検出で拾われる。

    Args:
        conn: SQLite接続オブジェクト
        count: 追加する大会数

    Returns:
        None
    """
    existing = set(get_tables(conn))
    totals = {"games": 0, "ends": 0, "shots": 0, "stones": 0}

    for i in range(count):
        # ── events（大会） ────────────────────────────────────────
        event_id = _insert_row(
            conn, "events",
            {"name": f"テストカップ{i + 1}", "year": 2026, "category": "test"},
        )

        # 子テーブルが無いDBもありうるので、存在チェックしながら下位を作る
        if "games" not in existing:
            continue

        # ── games（試合） ────────────────────────────────────────
        game_id = _insert_row(
            conn, "games",
            {
                "event_id": event_id,
                "page": 1,
                "team_red": "テスト赤",
                "team_yellow": "テスト黄",
                "final_score_red": 5,
                "final_score_yellow": 4,
            },
        )
        totals["games"] += 1

        if "ends" not in existing:
            continue

        # ── ends（エンド） ───────────────────────────────────────
        for end_no in range(1, ENDS_PER_GAME + 1):
            end_id = _insert_row(
                conn, "ends",
                {
                    "game_id": game_id,
                    "page": 1,
                    "number": end_no,
                    "color_hammer": "red",
                    "score_red": 1,
                    "score_yellow": 0,
                    # md DB にしか無いカラム。_insert_row が存在判定するので
                    # four DB では自動的に無視される
                    "is_power_play": 0,
                },
            )
            totals["ends"] += 1

            if "shots" not in existing:
                continue

            # ── shots（ショット） ────────────────────────────────
            for shot_no in range(1, SHOTS_PER_END + 1):
                # 赤黄交互に割り当てる
                color = "red" if shot_no % 2 == 1 else "yellow"
                shot_id = _insert_row(
                    conn, "shots",
                    {
                        "end_id": end_id,
                        "number": shot_no,
                        "color": color,
                        "team": "テスト赤" if color == "red" else "テスト黄",
                        "player_name": f"テスト選手{shot_no}",
                        "type": "draw",
                        "turn": "in",
                        "percent_score": 100,
                    },
                )
                totals["shots"] += 1

                if "stones" not in existing:
                    continue

                # ── stones（ストーン配置） ───────────────────────
                for stone_no in range(1, STONES_PER_SHOT + 1):
                    _insert_row(
                        conn, "stones",
                        {
                            "shot_id": shot_id,
                            "color": color,
                            "x": 0,
                            "y": 0,
                            "distance_from_center": 100,
                            "inhouse": 1,
                            "insheet": 1,
                            # normal(four) DB にしか無いカラム。存在しなければ無視
                            "shot_order": stone_no,
                        },
                    )
                    totals["stones"] += 1

    print(f"  events に {count} 件のダミー大会を追加")
    print(
        f"    └ 連動追加: games {totals['games']} / ends {totals['ends']} "
        f"/ shots {totals['shots']} / stones {totals['stones']} 件"
    )


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
        help="追加するダミー大会の件数（試合・エンド・ショット・ストーンも連動して追加）",
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
