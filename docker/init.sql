-- PostgreSQLコンテナ初回起動時に自動実行されるinitスクリプト
-- /docker-entrypoint-initdb.d/ に配置することで実行される
-- POSTGRES_USER で指定したユーザーが各DBのオーナーになる

CREATE DATABASE rb2db_md;
CREATE DATABASE rb2db_four;
