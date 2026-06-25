"""
scripts/notify_update.py

SQLiteファイルの差分を検出し、Gemini APIで自然言語に変換してSlackに通知するスクリプト。
update_db.sh から呼び出される。

使い方:
  # 差分検出あり（通常の更新時）
  PYTHONPATH=. uv run python scripts/notify_update.py \
      --target md \
      --new-file sqlite/md_260514.db \
      --prev-file sqlite/md.prev.db

  # 初回実行（旧ファイルなし）
  PYTHONPATH=. uv run python scripts/notify_update.py \
      --target md \
      --new-file sqlite/md_260514.db

  # テスト用: Slackに飛ばさず生成文だけ確認する
  PYTHONPATH=. uv run python scripts/notify_update.py \
      --target md \
      --new-file sqlite/test_new.db \
      --prev-file sqlite/test_base.db \
      --dry-run

  # テスト用: Gemini も呼ばず構造化差分とプロンプトだけ確認する
  PYTHONPATH=. uv run python scripts/notify_update.py \
      --target md \
      --new-file sqlite/test_new.db \
      --prev-file sqlite/test_base.db \
      --no-llm
"""

import argparse
import json
import os
import re
import sqlite3

import requests
from dotenv import load_dotenv
from google import genai

# .env を読み込み、GEMINI_API_KEY / SLACK_WEBHOOK_URL などを環境変数に載せる。
# load_dotenv() は .env の内容を os.environ に展開するだけで、値の中身には触れない。
# 既に環境変数が設定されている場合はそちらを優先する（上書きしない）。
load_dotenv()

# 差分検出・件数カウントの対象テーブル（存在しないテーブルはスキップ）
TARGET_TABLES = ["events", "games", "ends", "shots", "stones", "lsds"]

# ターゲット識別子から通知用の表示名への変換
TARGET_LABELS: dict[str, str] = {
    "md": "MD用DB",
    "four": "4人制用DB",
}

# 値修正検出の対象カラムと種別。
#   "discrete"  … 取りうる値が少数（スコア・フラグ・カテゴリカル）。
#                  値ごとの件数分布を prev/new で比較する。件数が1件でも変われば変化あり。
#   "continuous" … 連続値（座標・距離）。
#                  AVG/MIN/MAX の三点セットを prev/new で比較する。差が閾値超で変化あり。
COLUMN_KIND: dict[str, str] = {
    # 数値・離散値
    "shots.percent_score":          "discrete",
    "ends.score_red":               "discrete",
    "ends.score_yellow":            "discrete",
    "games.final_score_red":        "discrete",
    "games.final_score_yellow":     "discrete",
    "stones.inhouse":               "discrete",
    "stones.insheet":               "discrete",
    "ends.is_power_play":           "discrete",   # md のみ。0/1 二値
    # カテゴリカル（文字列だが離散値として同じロジックで処理）
    "shots.type":                   "discrete",
    "shots.turn":                   "discrete",
    "shots.color":                  "discrete",
    "ends.color_hammer":            "discrete",
    # 連続値（FLOAT）
    "stones.x":                     "continuous",
    "stones.y":                     "continuous",
    "stones.distance_from_center":  "continuous",
    "lsds.distance_cm":             "continuous",
}

# 連続値カラムごとの「変化あり」閾値（AVG の絶対差がこれを超えれば変化と判定）。
# 値域を考慮してカラムごとに設定する。実測後に調整する前提の初期値。
CONTINUOUS_THRESHOLD: dict[str, float] = {
    "stones.x":                     0.5,
    "stones.y":                     0.5,
    "stones.distance_from_center":  0.5,
    "lsds.distance_cm":             1.0,
}

# 自由文字列カラムの集合差分検出対象。
# 大会ごとに「出現する値の集合」を prev/new で比較し、消えた値・現れた値を出す。
# 件数が同じで集合が変わっていれば表記ゆれ修正とみなす。
STRING_COLUMNS: list[str] = [
    "games.team_red",
    "games.team_yellow",
    "shots.team",
    "lsds.team",
]


# ─── SQLiteユーティリティ ─────────────────────────────────────────────────────


def get_tables(conn: sqlite3.Connection) -> list[str]:
    """SQLiteデータベースのテーブル名一覧を取得する。

    Args:
        conn: SQLite接続オブジェクト

    Returns:
        list[str]: テーブル名のリスト（アルファベット順）
    """
    # sqlite_master はSQLiteが内部で管理するメタデータテーブル
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [row[0] for row in cursor.fetchall()]


def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """テーブルのカラム名一覧を取得する。

    Args:
        conn: SQLite接続オブジェクト
        table: テーブル名

    Returns:
        list[str]: カラム名のリスト

    Raises:
        ValueError: テーブル名が英数字・アンダースコア以外を含む場合
    """
    # テーブル名は識別子なのでプレースホルダーで渡せない
    # 英数字とアンダースコアのみ許可してSQLインジェクションを防ぐ
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError(f"不正なテーブル名: {table!r}")
    # PRAGMA table_info はカラムの定義情報を返す（row[1] がカラム名）
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """テーブルの行数を取得する。

    Args:
        conn: SQLite接続オブジェクト
        table: テーブル名（TARGET_TABLES に含まれる値のみ受け付ける）

    Returns:
        int: 行数

    Raises:
        ValueError: TARGET_TABLES に含まれないテーブル名が渡された場合
    """
    # テーブル名は識別子なのでプレースホルダーで渡せない
    # TARGET_TABLES のホワイトリストで許可済みの名前のみ実行する
    if table not in TARGET_TABLES:
        raise ValueError(f"許可されていないテーブル名: {table!r}")
    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
    return cursor.fetchone()[0]


def get_event_names(conn: sqlite3.Connection) -> set[str]:
    """eventsテーブルの大会名をすべて取得する。

    Args:
        conn: SQLite接続オブジェクト

    Returns:
        set[str]: 大会名の集合
    """
    try:
        cursor = conn.execute("SELECT name FROM events WHERE name IS NOT NULL")
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # テーブルが存在しない場合は空セットを返す
        return set()


# ─── 値修正検出（件数が変わらない更新の検出） ──────────────────────────────────


def _build_join_to_events(table: str) -> str:
    """テーブルから events まで JOIN する SQL フラグメントを返す。

    events.name でグルーピングするために、各テーブルから events まで
    外部キーを辿る JOIN 句を生成する。

    Args:
        table: 集計対象テーブル名（TARGET_TABLES のいずれか）

    Returns:
        str: "FROM <table> JOIN ... " の形式の SQL フラグメント

    Raises:
        ValueError: サポートしていないテーブルが指定された場合
    """
    # テーブルごとに events までの JOIN パスが決まっている
    if table == "events":
        return "FROM events"
    elif table == "games":
        return "FROM games JOIN events ON games.event_id = events.id"
    elif table == "ends":
        return (
            "FROM ends "
            "JOIN games ON ends.game_id = games.id "
            "JOIN events ON games.event_id = events.id"
        )
    elif table == "lsds":
        return (
            "FROM lsds "
            "JOIN games ON lsds.game_id = games.id "
            "JOIN events ON games.event_id = events.id"
        )
    elif table == "shots":
        return (
            "FROM shots "
            "JOIN ends ON shots.end_id = ends.id "
            "JOIN games ON ends.game_id = games.id "
            "JOIN events ON games.event_id = events.id"
        )
    elif table == "stones":
        return (
            "FROM stones "
            "JOIN shots ON stones.shot_id = shots.id "
            "JOIN ends ON shots.end_id = ends.id "
            "JOIN games ON ends.game_id = games.id "
            "JOIN events ON games.event_id = events.id"
        )
    else:
        raise ValueError(f"サポートしていないテーブル: {table!r}")


def _get_discrete_distribution(
    conn: sqlite3.Connection, table: str, column: str
) -> dict[str, dict[str, int]]:
    """大会ごとに離散値カラムの値分布（値→件数）を取得する。

    Args:
        conn: SQLite接続オブジェクト
        table: 対象テーブル名
        column: 対象カラム名

    Returns:
        dict[str, dict[str, int]]: {大会名: {値: 件数}} の辞書。
            テーブルまたはカラムが存在しない場合は空辞書。
    """
    try:
        join_sql = _build_join_to_events(table)
        # SQL識別子は validate_identifier 済みの COLUMN_KIND キーから来るので安全
        sql = (
            f"SELECT events.name, {table}.{column}, COUNT(*) "  # noqa: S608
            f"{join_sql} "
            f"WHERE {table}.{column} IS NOT NULL "
            f"GROUP BY events.name, {table}.{column}"
        )
        rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        # テーブルまたはカラムが存在しない（md/four スキーマ差など）
        return {}

    # {大会名: {値の文字列: 件数}} に変換
    result: dict[str, dict[str, int]] = {}
    for event_name, value, cnt in rows:
        result.setdefault(event_name, {})[str(value)] = cnt
    return result


def _get_continuous_stats(
    conn: sqlite3.Connection, table: str, column: str
) -> dict[str, dict[str, float]]:
    """大会ごとに連続値カラムの統計量（AVG/MIN/MAX）を取得する。

    Args:
        conn: SQLite接続オブジェクト
        table: 対象テーブル名
        column: 対象カラム名

    Returns:
        dict[str, dict[str, float]]: {大会名: {"avg": ..., "min": ..., "max": ...}} の辞書。
            テーブルまたはカラムが存在しない場合は空辞書。
    """
    try:
        join_sql = _build_join_to_events(table)
        sql = (
            f"SELECT events.name, AVG({table}.{column}), "  # noqa: S608
            f"MIN({table}.{column}), MAX({table}.{column}) "
            f"{join_sql} "
            f"WHERE {table}.{column} IS NOT NULL "
            f"GROUP BY events.name"
        )
        rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return {}

    return {
        event_name: {"avg": avg, "min": mn, "max": mx}
        for event_name, avg, mn, mx in rows
        if avg is not None
    }


def _get_string_sets(
    conn: sqlite3.Connection, table: str, column: str
) -> dict[str, set[str]]:
    """大会ごとに文字列カラムの出現値集合を取得する。

    Args:
        conn: SQLite接続オブジェクト
        table: 対象テーブル名
        column: 対象カラム名

    Returns:
        dict[str, set[str]]: {大会名: {値, ...}} の辞書。
            テーブルまたはカラムが存在しない場合は空辞書。
    """
    try:
        join_sql = _build_join_to_events(table)
        sql = (
            f"SELECT DISTINCT events.name, {table}.{column} "  # noqa: S608
            f"{join_sql} "
            f"WHERE {table}.{column} IS NOT NULL"
        )
        rows = conn.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return {}

    result: dict[str, set[str]] = {}
    for event_name, value in rows:
        result.setdefault(event_name, set()).add(str(value))
    return result


def detect_value_changes(prev_file: str, new_file: str) -> list[dict]:
    """件数が変わらない値修正を、大会ごとの集計比較で検出する。

    COLUMN_KIND に定義された各カラムについて、大会ごとの統計量（離散値は
    件数分布、連続値は AVG/MIN/MAX）を prev/new で比較し、変化があった
    カラムをリストアップする。

    変化量（離散値は変化件数合計、連続値は AVG の絶対差）の降順でソートして返す。
    連続値と離散値は種別内でそれぞれソートし、種別をまたぐ順位付けは行わない。

    Args:
        prev_file: 旧SQLiteファイルのパス
        new_file: 新SQLiteファイルのパス

    Returns:
        list[dict]: 変化が検出されたカラムごとの情報リスト。各要素は:
            - col_key (str): "table.column" 形式
            - kind (str): "discrete", "continuous", または "string"
            - changes (list[dict]): 変化があった大会ごとの詳細
              - discrete: {"event": ..., "diff": {値: (before, after)}}
              - continuous: {"event": ..., "before": stats, "after": stats}
              - string: {"event": ..., "removed": [...], "added": [...]}
            - sort_score (float): ソート用スコア（大きいほど変化量が大きい）
    """
    prev_conn = sqlite3.connect(prev_file)
    new_conn = sqlite3.connect(new_file)

    discrete_results: list[dict] = []
    continuous_results: list[dict] = []
    string_results: list[dict] = []

    try:
        for col_key, kind in COLUMN_KIND.items():
            table, column = col_key.split(".", 1)

            if kind == "discrete":
                prev_dist = _get_discrete_distribution(prev_conn, table, column)
                new_dist = _get_discrete_distribution(new_conn, table, column)

                # 両方に存在する大会のみ比較（片方にしかない大会は件数変化として扱われる）
                common_events = set(prev_dist) & set(new_dist)
                changes = []
                total_diff_count = 0

                for event_name in sorted(common_events):
                    p = prev_dist[event_name]
                    n = new_dist[event_name]
                    all_values = set(p) | set(n)
                    # 値ごとに before/after を比較
                    diffs = {
                        v: (p.get(v, 0), n.get(v, 0))
                        for v in all_values
                        if p.get(v, 0) != n.get(v, 0)
                    }
                    if diffs:
                        # 変化件数 = 変わった値の差の絶対値合計
                        cnt = sum(abs(after - before) for before, after in diffs.values())
                        total_diff_count += cnt
                        changes.append({"event": event_name, "diff": diffs})

                if changes:
                    # 変化量の大きい大会を先頭に並べる
                    changes.sort(
                        key=lambda c: sum(abs(a - b) for b, a in c["diff"].values()),
                        reverse=True,
                    )
                    discrete_results.append({
                        "col_key": col_key,
                        "kind": "discrete",
                        "changes": changes,
                        "sort_score": float(total_diff_count),
                    })

            elif kind == "continuous":
                prev_stats = _get_continuous_stats(prev_conn, table, column)
                new_stats = _get_continuous_stats(new_conn, table, column)

                threshold = CONTINUOUS_THRESHOLD.get(col_key, 0.5)
                common_events = set(prev_stats) & set(new_stats)
                changes = []
                total_avg_diff = 0.0

                for event_name in sorted(common_events):
                    p = prev_stats[event_name]
                    n = new_stats[event_name]
                    avg_diff = abs(n["avg"] - p["avg"])
                    # AVG が閾値超・AVG の符号変化・MIN/MAX の符号変化のいずれかで変化あり。
                    # AVG の符号変化により avg≈0 の x 座標の符号反転も検出できる。
                    sign_changed = (
                        (p["avg"] < 0) != (n["avg"] < 0)
                        or (p["min"] < 0) != (n["min"] < 0)
                        or (p["max"] < 0) != (n["max"] < 0)
                    )
                    if avg_diff > threshold or sign_changed:
                        total_avg_diff += avg_diff
                        changes.append({
                            "event": event_name,
                            "before": {k: round(v, 4) for k, v in p.items()},
                            "after": {k: round(v, 4) for k, v in n.items()},
                        })

                if changes:
                    changes.sort(
                        key=lambda c: abs(c["after"]["avg"] - c["before"]["avg"]),
                        reverse=True,
                    )
                    continuous_results.append({
                        "col_key": col_key,
                        "kind": "continuous",
                        "changes": changes,
                        "sort_score": total_avg_diff,
                    })

        # ── 文字列カラム（集合差分） ─────────────────────────────────
        for col_key in STRING_COLUMNS:
            table, column = col_key.split(".", 1)
            prev_sets = _get_string_sets(prev_conn, table, column)
            new_sets = _get_string_sets(new_conn, table, column)

            common_events = set(prev_sets) & set(new_sets)
            changes = []
            total_diff_count = 0

            for event_name in sorted(common_events):
                p = prev_sets[event_name]
                n = new_sets[event_name]
                removed = sorted(p - n)
                added = sorted(n - p)
                if removed or added:
                    total_diff_count += len(removed) + len(added)
                    changes.append({
                        "event": event_name,
                        "removed": removed,
                        "added": added,
                    })

            if changes:
                changes.sort(
                    key=lambda c: len(c["removed"]) + len(c["added"]),
                    reverse=True,
                )
                string_results.append({
                    "col_key": col_key,
                    "kind": "string",
                    "changes": changes,
                    "sort_score": float(total_diff_count),
                })

    finally:
        prev_conn.close()
        new_conn.close()

    # 種別内でソート（種別をまたぐ順位付けはしない）
    discrete_results.sort(key=lambda r: r["sort_score"], reverse=True)
    continuous_results.sort(key=lambda r: r["sort_score"], reverse=True)
    string_results.sort(key=lambda r: r["sort_score"], reverse=True)

    # 離散値 → 文字列 → 連続値の順にまとめて返す
    return discrete_results + string_results + continuous_results


# ─── 差分検出 ─────────────────────────────────────────────────────────────────


def detect_diff(prev_file: str, new_file: str, target: str) -> dict:
    """旧SQLiteと新SQLiteのスキーマ差分・データ差分を検出する。

    テーブルの追加/削除、カラムの追加/削除、各テーブルの行数変化、
    新規大会名を検出してまとめる。

    Args:
        prev_file: 旧SQLiteファイルのパス
        new_file: 新SQLiteファイルのパス
        target: DBターゲット（"md" または "four"）

    Returns:
        dict: スキーマ差分・データ差分を含む辞書
    """
    prev_conn = sqlite3.connect(prev_file)
    new_conn = sqlite3.connect(new_file)

    try:
        # ── スキーマ差分 ────────────────────────────────────────────

        prev_tables = set(get_tables(prev_conn))
        new_tables = set(get_tables(new_conn))

        # 追加/削除されたテーブル
        tables_added = sorted(new_tables - prev_tables)
        tables_removed = sorted(prev_tables - new_tables)

        # 共通テーブルのカラム差分
        columns_added: dict[str, list[str]] = {}
        columns_removed: dict[str, list[str]] = {}
        for table in sorted(prev_tables & new_tables):
            prev_cols = set(get_columns(prev_conn, table))
            new_cols = set(get_columns(new_conn, table))
            added = sorted(new_cols - prev_cols)
            removed = sorted(prev_cols - new_cols)
            if added:
                columns_added[table] = added
            if removed:
                columns_removed[table] = removed

        schema_changes = {
            "tables_added": tables_added,
            "tables_removed": tables_removed,
            "columns_added": columns_added,
            "columns_removed": columns_removed,
        }

        # ── データ差分 ──────────────────────────────────────────────

        data_changes: dict[str, dict] = {}
        for table in TARGET_TABLES:
            prev_exists = table in prev_tables
            new_exists = table in new_tables

            # どちらにも存在しないテーブルはスキップ
            if not prev_exists and not new_exists:
                continue

            before = count_rows(prev_conn, table) if prev_exists else 0
            after = count_rows(new_conn, table) if new_exists else 0
            entry: dict = {"before": before, "after": after, "diff": after - before}

            # eventsテーブルの新規追加大会名を列挙
            # 「どの大会が増えたか」は通知の主役になる定性情報なので必ず拾う
            if table == "events" and prev_exists and new_exists:
                prev_names = get_event_names(prev_conn)
                new_names = get_event_names(new_conn)
                entry["added_names"] = sorted(new_names - prev_names)

            data_changes[table] = entry

        # ── 値修正検出 ──────────────────────────────────────────────
        # 件数が変わらない既存行の値の変化を大会ごとの集計比較で検出する
        value_changes = detect_value_changes(prev_file, new_file)

        return {
            "target": target,
            "schema_changes": schema_changes,
            "data_changes": data_changes,
            "value_changes": value_changes,
        }

    finally:
        # 必ず接続を閉じる（例外が起きても閉じるために finally を使う）
        prev_conn.close()
        new_conn.close()


def detect_initial(new_file: str, target: str) -> dict:
    """初回実行時（旧ファイルなし）の全件数情報を取得する。

    Args:
        new_file: 新SQLiteファイルのパス
        target: DBターゲット（"md" または "four"）

    Returns:
        dict: is_initial=True と各テーブルの全件数を含む辞書
    """
    conn = sqlite3.connect(new_file)
    try:
        existing_tables = set(get_tables(conn))
        data_counts: dict[str, int] = {}
        for table in TARGET_TABLES:
            if table in existing_tables:
                data_counts[table] = count_rows(conn, table)
        return {
            "target": target,
            "is_initial": True,
            "data_counts": data_counts,
        }
    finally:
        conn.close()


# ─── 通知文の生成 ─────────────────────────────────────────────────────────────


def has_any_change(diff: dict) -> bool:
    """差分情報に何らかの変化が含まれるか判定する。

    スキーマ変更・件数増減・追加大会名・値修正のいずれかがあれば True。
    すべて変化なしの場合のみ False を返す。

    Args:
        diff: detect_diff の返り値

    Returns:
        bool: 変化が1件以上あれば True
    """
    sc = diff.get("schema_changes", {})
    if any([
        sc.get("tables_added"),
        sc.get("tables_removed"),
        sc.get("columns_added"),
        sc.get("columns_removed"),
    ]):
        return True

    for entry in diff.get("data_changes", {}).values():
        if entry.get("diff", 0) != 0:
            return True
        if entry.get("added_names"):
            return True

    if diff.get("value_changes"):
        return True

    return False


def format_no_change_message(diff: dict) -> str:
    """変化なし時の定型通知文を生成する（Gemini API を使わない）。

    Args:
        diff: detect_diff の返り値

    Returns:
        str: Slack に投稿する通知文字列
    """
    target_label = TARGET_LABELS.get(diff["target"], diff["target"])
    return f"【CurlingDB更新確認】{target_label}\n前回からの変更は検出されませんでした。"


def format_initial_message(diff: dict) -> str:
    """初回登録時の定型通知文を生成する（Gemini API を使わない）。

    Args:
        diff: detect_initial の返り値

    Returns:
        str: Slack に投稿する通知文字列
    """
    target_label = TARGET_LABELS.get(diff["target"], diff["target"])
    lines = [f"【CurlingDB初回登録】{target_label}"]
    for table, count in diff["data_counts"].items():
        lines.append(f"・{table}: {count:,} 件")
    return "\n".join(lines)


# ─── Gemini API ───────────────────────────────────────────────────────────────


def build_prompt(diff: dict) -> str:
    """差分情報からGeminiへのプロンプトを生成する。

    Args:
        diff: detect_diff または detect_initial の返り値

    Returns:
        str: Gemini API に渡すプロンプト文字列
    """
    target = diff["target"]
    target_label = TARGET_LABELS.get(target, target)
    return f"""
以下はカーリング試合データベース（{target_label}）の更新差分情報です。
これを研究室メンバー向けに簡潔でわかりやすい日本語の通知文に変換してください。

この通知で読み手が知りたいのは「何が新しく増えたか・構造がどう変わったか・
既存データのどこが修正されたか」という定性的な事実です。
具体的な件数は主役ではなく、補足として軽く触れる程度で十分です。

要件（重要度の高い順）:
- 冒頭に「【CurlingDB更新通知】{target_label}」というタイトルを入れる
- 「今回の更新内容は以下の通りです。」から本文を開始する。
- 【最優先】追加された大会名（added_names）があれば、必ず具体的に列挙する
- 【最優先】スキーマ変更（テーブル・カラムの追加/削除）があれば必ず明記する。
  特にカラム追加は「どのテーブルに何というカラムが増えたか」を具体的に書く
- 【重要】value_changes に変化がある場合、どの大会のどのカラムがどう変わったかを
  傾向として書く。連続値は統計量（AVG/MIN/MAX）の変化から傾向を読み取って表現する。
  離散値・カテゴリカルは値ごとの件数の増減から傾向を表現する
- データ件数の増減は「補足」として軽く触れる程度に留める（数字の羅列にしない）
- 箇条書きを使う場合は「・ 」（記号＋半角スペース）の形式にする
- 追加要素が無い項目（added_names が空、スキーマ変更なし等）はわざわざ言及しない
- 全体で300文字以内に収める

差分情報:
{json.dumps(diff, ensure_ascii=False, indent=2)}
"""


def call_gemini(prompt: str) -> str:
    """Gemini APIにプロンプトを送り、生成されたテキストを返す。

    Args:
        prompt: Gemini API に渡すプロンプト文字列

    Returns:
        str: Gemini API が生成した通知文

    Raises:
        ValueError: GEMINI_API_KEY が未設定の場合
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("環境変数 GEMINI_API_KEY が設定されていません")

    # google-genai（新SDK）の使い方: Client を作成してモデルを呼び出す
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=prompt,
    )
    return response.text


# ─── Slack通知 ────────────────────────────────────────────────────────────────


def post_to_slack(message: str) -> None:
    """Slack Incoming Webhookにメッセージを投稿する。

    Args:
        message: Slackに投稿するメッセージ文字列

    Raises:
        ValueError: SLACK_WEBHOOK_URL が未設定の場合、または通知失敗の場合
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise ValueError("環境変数 SLACK_WEBHOOK_URL が設定されていません")

    payload = {"text": message}
    # timeout=10: 10秒以内に応答がなければ例外を発生させる
    response = requests.post(webhook_url, json=payload, timeout=10)
    if response.status_code != 200:
        raise ValueError(f"Slack通知失敗: {response.status_code} {response.text}")


# ─── エントリーポイント ───────────────────────────────────────────────────────


def main() -> None:
    """引数を解析して差分検出・Gemini生成・Slack通知を実行する。"""
    # argparse: コマンドライン引数のパースライブラリ（標準ライブラリ）
    parser = argparse.ArgumentParser(
        description="SQLite差分を検出してSlackに通知するスクリプト"
    )
    parser.add_argument(
        "--target", required=True, choices=["md", "four"],
        help="DBターゲット（md または four）",
    )
    parser.add_argument(
        "--new-file", required=True,
        help="新しいSQLiteファイルのパス",
    )
    parser.add_argument(
        "--prev-file", default=None,
        help="旧SQLiteファイルのパス（省略時は初回実行として件数のみ通知）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Slackに投稿せず、生成された通知文を標準出力に出すだけにする（テスト用）",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Gemini APIを呼ばず、構造化された差分JSONの確認だけ行う（テスト用）",
    )
    args = parser.parse_args()

    # ── ファイル存在チェック ────────────────────────────────────────
    if not os.path.isfile(args.new_file):
        print(f"エラー: 新SQLiteファイルが見つかりません: {args.new_file}")
        raise SystemExit(1)

    if args.prev_file is not None and not os.path.isfile(args.prev_file):
        print(f"エラー: 旧SQLiteファイルが見つかりません: {args.prev_file}")
        raise SystemExit(1)

    # ── 差分情報の取得 ────────────────────────────────────────────
    if args.prev_file is not None:
        print("差分を検出中...")
        diff = detect_diff(args.prev_file, args.new_file, args.target)
    else:
        print("初回実行: 全件数を取得中...")
        diff = detect_initial(args.new_file, args.target)

    # 確認用に差分情報を標準出力に出力
    print("差分情報:")
    print(json.dumps(diff, ensure_ascii=False, indent=2))

    # ── --no-llm: 構造化差分の確認だけ行う ──────────────────────────
    # Gemini も Slack も呼ばず、上で出力した差分JSONの確認に留める。
    # プロンプトに渡る構造化データそのものを検証したいときに使う。
    if args.no_llm:
        if not diff.get("is_initial"):
            # 実際に Gemini に渡るプロンプト文字列も確認できるようにする
            print("\n生成されるプロンプト:")
            print(build_prompt(diff))
        print("\n--no-llm 指定のため、通知文生成・Slack投稿はスキップしました")
        return

    # ── 通知文の生成 ──────────────────────────────────────────────
    # 初回登録は定型文、完全変化なしも定型文、差分更新は Gemini API で自然文を生成する
    if diff.get("is_initial"):
        print("初回登録: 定型文を生成...")
        message = format_initial_message(diff)
    elif not has_any_change(diff):
        # スキーマ変更・件数増減・追加大会名・値修正のいずれも検出されなかった場合
        # Gemini を呼ばずに定型文で通知する（コスト節約・高速化）
        print("変化なし: 定型文を生成（Gemini スキップ）...")
        message = format_no_change_message(diff)
    else:
        print("Gemini APIで通知文を生成中...")
        prompt = build_prompt(diff)
        message = call_gemini(prompt)
    print(f"生成された通知文:\n{message}")

    # ── Slackに投稿 ─────────────────────────────────────────────────
    # --dry-run のときは投稿せず、生成文の確認だけで終える
    if args.dry_run:
        print("\n--dry-run 指定のため、Slack投稿はスキップしました")
        return

    print("Slackに投稿中...")
    post_to_slack(message)
    print("Slack通知完了")


if __name__ == "__main__":
    main()
