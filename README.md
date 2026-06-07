# ResultsBook2DB-API

[CURLIT](https://curlit.com/) 社が提供するカーリングの公式記録集 (Results Book) を PostgreSQL データベースから取得する REST API。

## データ概要

2つのデータベースに分かれています。

| DB | カテゴリ | 大会数 | 試合数 | ストーン座標数 |
|---|---|---:|---:|---:|
| four | Men / Women / Junior | 42 | 2,241 | 1,152,797 |
| md | ミックスダブルス | 13 | 1,419 | 417,850 |

## エンドポイント

`/v1/four/` と `/v1/md/` に同じ構造のエンドポイントがあります。

| メソッド | URL | 説明 |
|---|---|---|
| GET | `/v1/four/events` | 大会一覧 |
| GET | `/v1/four/events/{id}` | 大会1件 |
| GET | `/v1/four/events/{id}/games` | 大会の試合一覧 |
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

### 共通クエリパラメータ

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `limit` | 50 | 取得件数（1〜1000） |
| `offset` | 0 | 取得開始位置 |
| `sort` | `id` | ソート対象カラム |
| `order` | `asc` | ソート方向（`asc` / `desc`） |

テーブルごとのフィルタパラメータや詳細なレスポンス形式は `/docs` を参照してください。

## 使用例

以下の例では `BASE_URL` をサーバーのアドレスに置き換えてください。

### 大会一覧を取得する

```bash
curl "$BASE_URL/v1/four/events"
```

### 特定の大会の試合一覧を取得する

```bash
# 大会名・年で絞り込んで ID を確認する
curl "$BASE_URL/v1/four/events?name=WMDCC&year=2024"

# その ID の試合一覧を取得する
curl "$BASE_URL/v1/four/events/1/games"
```

### ページネーションとソートを使う

```bash
# 新しい順に10件取得する（2件目から）
curl "$BASE_URL/v1/four/games?limit=10&offset=0&sort=id&order=desc"
```

### 特定の試合のエンドデータを取得する

```bash
# game_id=1 の試合の全エンドを取得する
curl "$BASE_URL/v1/four/ends?game_id=1"
```

### ストーン座標データを取得する

```bash
# shot_id=1 の投球後のストーン座標を取得する
curl "$BASE_URL/v1/four/shots/1/stones"
```

### ミックスダブルス（md）のデータを取得する

```bash
# md DB の大会一覧（four を md に変えるだけ）
curl "$BASE_URL/v1/md/events"

# パワープレイが使われたエンドを絞り込む（md のみ）
curl "$BASE_URL/v1/md/ends?is_power_play=1"
```

## 技術スタック

- Python 3.12 / FastAPI
- SQLAlchemy（ORM）
- PostgreSQL 18
- Docker / docker-compose
- uv（パッケージ管理）
