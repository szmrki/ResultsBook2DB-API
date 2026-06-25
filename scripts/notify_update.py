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

        return {
            "target": target,
            "schema_changes": schema_changes,
            "data_changes": data_changes,
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

この通知で読み手が知りたいのは「何が新しく増えたか・構造がどう変わったか」という
定性的な事実です。具体的な件数は主役ではなく、補足として軽く触れる程度で十分です。

要件（重要度の高い順）:
- 冒頭に「【CurlingDB更新通知】{target_label}」というタイトルを入れる
- 【最優先】追加された大会名（added_names）があれば、必ず具体的に列挙する
- 【最優先】スキーマ変更（テーブル・カラムの追加/削除）があれば必ず明記する。
  特にカラム追加は「どのテーブルに何というカラムが増えたか」を具体的に書く
- データ件数の増減は「補足」として軽く触れる程度に留める（数字の羅列にしない）。
  「○試合分のデータが追加されました」のように規模感が伝われば十分
- 追加要素が無い項目（added_names が空、スキーマ変更なし等）はわざわざ言及しない
- 全体で200文字以内に収める

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
    # 初回登録は定型文、差分更新は Gemini API で自然文を生成する
    if diff.get("is_initial"):
        print("初回登録: 定型文を生成...")
        message = format_initial_message(diff)
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
