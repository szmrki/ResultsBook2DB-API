# ベースイメージ: Python 3.12 slim（軽量版）
# DockerHub から公式イメージを取得する
FROM python:3.12-slim

# コンテナ内の作業ディレクトリを /app に設定
# 以降のコマンドはすべてこのディレクトリで実行される
WORKDIR /app

# uv をインストール
# ghcr.io/astral-sh/uv という別イメージから /uv バイナリだけをコピーする
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 依存ファイルを先にコピー（キャッシュ効率化のため）
# app/ より先にコピーすることで、コードだけ変更した場合に
# パッケージ再インストールをスキップできる（Dockerレイヤーキャッシュの活用）
COPY pyproject.toml uv.lock* ./

# 依存パッケージをインストール
# --frozen  : uv.lock の内容を厳密に使う（バージョンを勝手に変えない）
# --no-dev  : 開発用パッケージは含めない
# --no-cache: キャッシュを残さずイメージサイズを小さくする
RUN uv sync --frozen --no-dev --no-cache

# アプリケーションコードをコンテナにコピー
COPY app/ ./app/

# ポート8000を外部に公開することを宣言（ドキュメント的な意味合い）
# 実際のポートマッピングは docker-compose.yml で行う
EXPOSE 8000

# コンテナ起動時のデフォルトコマンド
# docker-compose.yml の command: で上書き可能
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]