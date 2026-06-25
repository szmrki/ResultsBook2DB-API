#!/bin/bash
# 更新通知のテストを一括実行するラッパースクリプト
#
# shrink（軽量ベース作成）→ mutate（変更を加えた new 作成）→ notify（差分通知確認）
# の3ステップを1コマンドで通す。各スクリプトの詳細は memo/TESTING.md を参照。
#
# 使い方:
#   ./scripts/run_notify_test.sh <mode> [mutateオプション...]
#
#   <mode>:
#     no-llm    差分JSONとプロンプトだけ確認（Gemini/Slackを呼ばない・API不要）
#     dry-run   自然言語生成まで実行（GEMINI_API_KEY必要・Slackには飛ばさない）
#
#   [mutateオプション] は make_test_db.py mutate にそのまま渡る:
#     --add-events N            ダミー大会を N 件追加（試合・エンド・ショット・ストーンも連動）
#     --add-column TABLE:COLUMN 謎カラムを追加（複数指定可）
#     --add-table NAME          テーブルを追加（複数指定可）
#
# 例:
#   ./scripts/run_notify_test.sh no-llm --add-events 1 --add-column shots:foo
#   ./scripts/run_notify_test.sh dry-run --add-events 2 --add-table experimental

set -e  # エラーが出たら即終了

# ── 設定（必要なら環境変数で上書き可） ──────────────────────────────
# SRC_DB:    shrink の元にする実DB
# BASE_DB:   生成する軽量ベース（prev/更新前）
# NEW_DB:    生成する new（更新後）
# TARGET:    notify_update.py に渡す --target（md または four）
# SHRINK_EVENTS: shrink で残す大会数
SRC_DB="${SRC_DB:-sqlite/normal_260611.db}"
BASE_DB="${BASE_DB:-sqlite/test_base.db}"
NEW_DB="${NEW_DB:-sqlite/test_new.db}"
TARGET="${TARGET:-four}"
SHRINK_EVENTS="${SHRINK_EVENTS:-2}"

# ── 引数チェック ────────────────────────────────────────────────
if [ "$#" -lt 1 ]; then
    echo "使い方: $0 <no-llm|dry-run> [mutateオプション...]"
    echo "例: $0 no-llm --add-events 1 --add-column shots:foo"
    exit 1
fi

MODE=$1
shift  # 残りの引数（$@）は mutate にそのまま渡す

# mode に応じて notify_update.py に渡すフラグを決める
case "$MODE" in
    no-llm)
        NOTIFY_FLAG="--no-llm"
        ;;
    dry-run)
        NOTIFY_FLAG="--dry-run"
        ;;
    *)
        echo "エラー: mode は 'no-llm' または 'dry-run' を指定してください（指定値: ${MODE}）"
        exit 1
        ;;
esac

# ── 1. 軽量ベースDB（prev）の用意 ─────────────────────────────────
# 既に存在すれば使い回す（毎回 shrink すると重いため）。
# 作り直したい場合は事前に test_base.db を削除するか REBUILD_BASE=1 を指定。
if [ "${REBUILD_BASE:-0}" = "1" ] || [ ! -f "$BASE_DB" ]; then
    echo "=== [1/3] 軽量ベースDBを作成: ${BASE_DB} (events=${SHRINK_EVENTS}) ==="
    if [ ! -f "$SRC_DB" ]; then
        echo "エラー: 元DBが見つかりません: ${SRC_DB}"
        echo "       SRC_DB 環境変数で実DBのパスを指定してください"
        exit 1
    fi
    python3 scripts/make_test_db.py shrink "$SRC_DB" "$BASE_DB" --events "$SHRINK_EVENTS"
else
    echo "=== [1/3] 既存のベースDBを使用: ${BASE_DB} ==="
    echo "      （作り直すには REBUILD_BASE=1 を指定）"
fi
echo ""

# ── 2. 変更を加えた new DB の作成 ────────────────────────────────
echo "=== [2/3] new DBを作成: ${NEW_DB} ==="
echo "      mutateオプション: $*"
python3 scripts/make_test_db.py mutate "$BASE_DB" "$NEW_DB" "$@"
echo ""

# ── 3. 差分通知の確認 ────────────────────────────────────────────
echo "=== [3/3] 差分通知を確認 (${NOTIFY_FLAG}) ==="
# uv run で実行すると依存（google-genai 等）が解決される。
# no-llm の場合は Gemini を呼ばないが、import 解決のため同じ実行系で統一する。
PYTHONPATH=. uv run python scripts/notify_update.py \
    --target "$TARGET" \
    --prev-file "$BASE_DB" \
    --new-file "$NEW_DB" \
    "$NOTIFY_FLAG"
