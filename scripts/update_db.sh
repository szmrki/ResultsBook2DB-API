#!/bin/bash
# DB更新スクリプト
# SQLiteファイルをコンテナにコピーしてPostgreSQLに移行し、Slackに通知する
#
# 使い方:
#   ./scripts/update_db.sh md sqlite/md_260514.db
#   ./scripts/update_db.sh four sqlite/normal_260502.db

set -e  # エラーが出たら即終了

# ── 引数チェック ────────────────────────────────────────────────
if [ "$#" -ne 2 ]; then
    echo "使い方: $0 <md|four> <SQLiteファイルパス>"
    echo "例: $0 md sqlite/md_260514.db"
    echo "例: $0 four sqlite/normal_260502.db"
    exit 1
fi

TARGET=$1       # md または four
SQLITE_FILE=$2  # SQLiteファイルのパス

# ── 入力値チェック ──────────────────────────────────────────────
if [ "$TARGET" != "md" ] && [ "$TARGET" != "four" ]; then
    echo "エラー: ターゲットは 'md' または 'four' を指定してください"
    exit 1
fi

if [ ! -f "$SQLITE_FILE" ]; then
    echo "エラー: SQLiteファイルが見つかりません: $SQLITE_FILE"
    exit 1
fi

# ── .envの読み込み ──────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "エラー: .envファイルが見つかりません"
    exit 1
fi
set -a  # 以降の変数代入を自動的に export する
source .env
set +a  # 自動 export を解除

# ── DB名の設定 ──────────────────────────────────────────────────
if [ "$TARGET" = "md" ]; then
    DB_NAME="rb2db_md"
else
    DB_NAME="rb2db_four"
fi

# PG_URL はコマンド引数に渡すとプロセス一覧にパスワードが露出するため、
# 環境変数 DATABASE_URL として渡す。migrate_sqlite_to_pg.py 側で読み込む。
DATABASE_URL="postgresql://curling:${POSTGRES_PASSWORD}@db:5432/${DB_NAME}"
export DATABASE_URL

# ── prev ファイルパスの設定 ──────────────────────────────────────
# ターゲットごとに固定パスで管理する（入力ファイル名に依存しない）
# これにより normal_260610.db → normal_260611.db のようにファイル名が変わっても
# 前回実行時のファイルと正しく比較できる
PREV_FILE="sqlite/${TARGET}.prev.db"

# ── 処理開始 ────────────────────────────────────────────────────
echo "=== DB更新開始: ${TARGET} ==="
echo "SQLiteファイル: ${SQLITE_FILE}"
echo "移行先DB: ${DB_NAME}"
echo ""

# 1. コンテナ内にsqliteディレクトリを作成
echo "[1/4] コンテナにSQLiteファイルをコピー中..."
docker exec rb2db-api mkdir -p /app/sqlite
BASENAME=$(basename "$SQLITE_FILE")
docker cp "$SQLITE_FILE" "rb2db-api:/app/sqlite/${BASENAME}"
echo "      完了"

# 2. 移行スクリプト実行
echo "[2/4] データ移行中..."
# DATABASE_URL を環境変数としてコンテナに渡す（--pg-url 引数を使わない）
docker exec -it -e DATABASE_URL="${DATABASE_URL}" rb2db-api \
    sh -c "PYTHONPATH=/app uv run python scripts/migrate_sqlite_to_pg.py \
    sqlite/$(basename "$SQLITE_FILE")"

# 3. 完了確認
echo ""
echo "[3/4] 動作確認..."
if [ "$TARGET" = "md" ]; then
    curl -s http://localhost:8000/v1/md/events?limit=1 | python3 -m json.tool
else
    curl -s http://localhost:8000/v1/four/events?limit=1 | python3 -m json.tool
fi

# 4. Slack通知
echo "[4/4] Slack通知中..."
if [ -f "$PREV_FILE" ]; then
    # prev ファイルがある場合は前回実行時のファイルとの差分を通知
    PYTHONPATH=. uv run python scripts/notify_update.py \
        --target "$TARGET" \
        --new-file "$SQLITE_FILE" \
        --prev-file "$PREV_FILE"
else
    # 初回実行時（prev がない）は全件数のみ通知
    echo "      前回ファイルが存在しないため差分検出をスキップ（初回実行）"
    PYTHONPATH=. uv run python scripts/notify_update.py \
        --target "$TARGET" \
        --new-file "$SQLITE_FILE"
fi

# 5. 今回のファイルを次回比較用として保存
#    通知が終わってから保存することで、次回実行時に正しく前回分として使われる
cp "$SQLITE_FILE" "$PREV_FILE"
echo "次回比較用ファイルを保存: ${PREV_FILE}"

echo ""
echo "=== DB更新完了: ${TARGET} ==="
