-- rb2db MCP サーバー用 read-only ロールのセットアップ（冪等）
--
-- MCP サーバーはこのロールで DB に接続する。仮に SQL 側の検証を回避されても、
-- ロール自体が read-only + タイムアウト付きのため、書き込み・長時間クエリを DB が拒否する。
--
-- ▼ 適用方法
--   docker/init.sql はボリューム新規作成時のみ実行されるため、稼働中DBには
--   このSQLを手動で流す。rb2db_md / rb2db_four の各DBに対して実行する必要がある
--   （テーブル権限はDBごとに独立しているため）。
--
--     psql -U <admin> -d rb2db_md   -f docker/setup_readonly_role.sql
--     psql -U <admin> -d rb2db_four  -f docker/setup_readonly_role.sql
--
--   ロール本体（CREATE ROLE）はクラスタ全体で共有されるため、2回流しても冪等。
--
-- ▼ ロール名・パスワード
--   ロール名は rb2db_readonly 固定。パスワードは別途 ALTER ROLE で設定する:
--     ALTER ROLE rb2db_readonly PASSWORD '実際のパスワード';
--   （このSQLはパスワードを設定しない。CI/ログにパスワードを残さないため）

-- ── 1. ロールの作成（存在しなければ作る） ──────────────────────────
-- CREATE ROLE は IF NOT EXISTS を持たないため、DO ブロックで存在チェックする。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rb2db_readonly') THEN
        CREATE ROLE rb2db_readonly LOGIN;
    END IF;
END
$$;

-- ── 2. ロールのデフォルト挙動（主たる防御線） ──────────────────────
-- このロールで開いた全トランザクションを read-only にし、長時間クエリを打ち切る。
-- ALTER ROLE ... SET は上書きなので繰り返し実行しても冪等。
ALTER ROLE rb2db_readonly SET default_transaction_read_only = on;
ALTER ROLE rb2db_readonly SET statement_timeout = '30s';

-- ── 3. 接続・参照権限（このSQLを流した現在のDBに対して付与） ────────
-- GRANT は冪等（既にあってもエラーにならない）。
-- 接続中のDBに対して CONNECT を付与する。psql の :DBNAME は接続先DB名に展開される
-- 組み込み変数なので、md / four どちらに流しても正しいDBに付与される。
GRANT CONNECT ON DATABASE :"DBNAME" TO rb2db_readonly;
GRANT USAGE ON SCHEMA public TO rb2db_readonly;

-- 既存の全テーブルへの SELECT を付与。
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rb2db_readonly;

-- 今後 public スキーマに作られるテーブルにも自動で SELECT を付与する。
-- （移行スクリプトでテーブルを作り直しても権限付与を忘れないための保険）
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rb2db_readonly;
