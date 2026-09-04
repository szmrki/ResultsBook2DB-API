# ResultsBook2DB-API

[CURLIT](https://curlit.com/) 社が提供するカーリングの公式記録集 (Results Book) を PostgreSQL データベースから取得する REST API。

## データ概要

2つのデータベースに分かれています。

| DB | カテゴリ | 大会数 | 試合数 | ショット数 | ストーン座標数 |
|---|---|---:|---:|---:|---:|
| four | Men / Women / Junior | 42 | 2,241 | 274,283 | 1,152,837 |
| md | ミックスダブルス | 13 | 1,419 | 73,216 | 417,871 |

## エンドポイント

`/v1/four/` と `/v1/md/` に同じ構造のエンドポイントがあります。

| メソッド | URL | 説明 |
|---|---|---|
| GET | `/v1/four/events` | 大会一覧 |
| GET | `/v1/four/events/{id}` | 大会1件 |
| GET | `/v1/four/events/{id}/games` | 大会の試合一覧 |
| GET | `/v1/four/events/{id}/standings` | 大会の順位表 |
| GET | `/v1/four/events/{id}/rosters` | 大会の出場選手一覧 |
| GET | `/v1/four/games` | 試合一覧 |
| GET | `/v1/four/games/{id}` | 試合1件 |
| GET | `/v1/four/games/{id}/ends` | 試合のエンド一覧 |
| GET | `/v1/four/games/{id}/lsds` | 試合のLSD一覧 |
| GET | `/v1/four/ends` | エンド一覧 |
| GET | `/v1/four/ends/{id}` | エンド1件 |
| GET | `/v1/four/ends/{id}/shots` | エンドのショット一覧 |
| GET | `/v1/four/shots` | ショット一覧 |
| GET | `/v1/four/shots/{id}` | ショット1件 |
| GET | `/v1/four/shots/{id}/stones` | ショット後のストーン座標一覧 |
| GET | `/v1/four/stones` | ストーン一覧 |
| GET | `/v1/four/stones/{id}` | ストーン1件 |
| GET | `/v1/four/lsds` | LSD一覧 |
| GET | `/v1/four/lsds/{id}` | LSD1件 |
| GET | `/v1/four/standings` | 順位一覧 |
| GET | `/v1/four/standings/{id}` | 順位1件 |
| GET | `/v1/four/rosters` | 出場選手一覧 |
| GET | `/v1/four/rosters/{id}` | 出場選手1件 |

md / four のどちらにも属さない共通エンドポイント:

| メソッド | URL | 説明 |
|---|---|---|
| GET | `/v1/notes` | 前提知識ドキュメントの一覧 |
| GET | `/v1/notes/{doc}` | 前提知識ドキュメントの本文（Markdown） |

詳細な注意点・スキーマ解説は `GET /v1/notes` から取得できます。

### 共通クエリパラメータ

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `limit` | 50 | 取得件数（1〜100000） |
| `offset` | 0 | 取得開始位置 |
| `sort` | `id` | ソート対象カラム |
| `order` | `asc` | ソート方向（`asc` / `desc`） |

テーブルごとのフィルタパラメータや詳細なレスポンス形式は [API ドキュメント](https://szmrki.github.io/ResultsBook2DB-API/) を参照してください。

> API 本体は研究室内限定公開です。ドキュメントはスキーマ定義のみを公開しています。

## MCP サーバー

REST API に加えて、AIコーディングツール（Claude Code 等）から
**最新のDBに read-only SQL で直接問い合わせる** ための MCP サーバーを提供しています。
ページネーションの多重往復を避け、集計・結合を伴う探索的分析に向いています。

提供するツール:

- `run_query(sql, db)` — 任意の read-only SQL を実行（`SELECT` / `WITH` のみ）
- `get_schema(db)` — テーブル定義・カラムの意味・md/four 差分を取得

スキーマ解説・SQL上の注意点・集計定義は MCP リソースとして同梱しています。
同じ内容は REST API の `GET /v1/notes/{doc}` からも取得できます。

> MCP サーバー本体も研究室内限定公開です。

## 技術スタック

| 領域 | 使用技術 |
|---|---|
| 言語 / フレームワーク | Python 3.12 / FastAPI |
| データベース | PostgreSQL 18 / SQLAlchemy（ORM） |
| AI ツール連携 | MCP（Model Context Protocol） |
| インフラ | Docker / docker-compose |
| 公開・認証 | Cloudflare Tunnel / Access |
| 開発環境 | uv（パッケージ管理）/ Ruff / mypy / pytest |

## データの取り扱いと免責事項

* 本ツールは、カーリングの戦術分析を目的とした **研究・分析用途の個人開発プロジェクト** です。[CURLIT](https://curlit.com/) 社および [WCF (World Curling Federation)](https://worldcurling.org/) とは一切関係のない **非公式** ツールです。
* **本リポジトリにはデータベースの実体 (`.db` / PDF 等) を一切含みません。** 公開しているのは API のソースコードとスキーマ定義のみです。

## ライセンス

本ソフトウェアは **MIT License** の下で公開されています。詳細は [LICENSE](LICENSE) を参照してください。
