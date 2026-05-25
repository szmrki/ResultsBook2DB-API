#!/bin/bash
# DB更新スクリプト
# SQLiteファイルをコンテナにコピーしてPostgreSQLに移行する
#
# 使い方:
#   ./scripts/update_db.sh md memo/md_260514.db
#   ./scripts/update_db.sh four memo/normal_260502.db

set -e  # エラーが出たら即終了

# ── 引数チェック ────────────────────────────────────────────────
if [ "$#" -ne 2 ]; then
    echo "使い方: $0 <md|four> <SQLiteファイルパス>"
    echo "例: $0 md memo/md_260514.db"
    echo "例: $0 four memo/normal_260502.db"
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
source .env

# ── DB名の設定 ──────────────────────────────────────────────────
if [ "$TARGET" = "md" ]; then
    DB_NAME="rb2db_md"
else
    DB_NAME="rb2db_four"
fi

PG_URL="postgresql://curling:${POSTGRES_PASSWORD}@db:5432/${DB_NAME}"

# ── 処理開始 ────────────────────────────────────────────────────
echo "=== DB更新開始: ${TARGET} ==="
echo "SQLiteファイル: ${SQLITE_FILE}"
echo "移行先DB: ${DB_NAME}"
echo ""

# 1. コンテナ内にmemoディレクトリを作成
echo "[1/3] コンテナにSQLiteファイルをコピー中..."
docker exec rb2db-api mkdir -p /app/memo
docker cp "$SQLITE_FILE" rb2db-api:/app/memo/$(basename "$SQLITE_FILE")
echo "      完了"

# 2. 移行スクリプト実行
echo "[2/3] データ移行中..."
docker exec -it rb2db-api \
    sh -c "PYTHONPATH=/app uv run python scripts/migrate_sqlite_to_pg.py \
    memo/$(basename "$SQLITE_FILE") --pg-url ${PG_URL}"

# 3. 完了確認
echo ""
echo "[3/3] 動作確認..."
if [ "$TARGET" = "md" ]; then
    curl -s http://localhost:8000/v1/md/events?limit=1 | python3 -m json.tool
else
    curl -s http://localhost:8000/v1/four/events?limit=1 | python3 -m json.tool
fi

echo ""
echo "=== DB更新完了: ${TARGET} ==="