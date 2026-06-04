"""
ログ設定モジュール。

構造化ログの設定を行い、アプリケーション全体で統一されたログを出力する。
JSON形式でのログ出力にも対応しており、ログ解析ツールとの連携が容易。

ここでやること:
  1. ログフォーマッタの設定（標準出力・JSON出力）
  2. ログレベルの設定（環境変数から取得）
  3. Logger インスタンスの作成
"""

import json
import logging
import os
from datetime import datetime, timezone
from logging import LogRecord
from typing import Any


class JSONFormatter(logging.Formatter):
    """ログレコードをJSON形式に変換するカスタムフォーマッタ。

    本番環境（Docker/Kubernetes）ではログを JSON で吐くことで、
    Datadog や CloudWatch などのログ解析ツールで構造化ログとして扱える。

    Attributes:
        _timestamp_format: タイムスタンプのフォーマット文字列
    """

    def format(self, record: LogRecord) -> str:
        """LogRecord を JSON 文字列に変換する。

        Args:
            record: ログレコード

        Returns:
            JSON 形式のログ文字列
        """
        # ログレコードの情報を辞書に詰める
        # isoformat(timespec="milliseconds") で "2026-06-04T12:34:56.789+00:00" 形式になる
        log_obj: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 例外情報がある場合は追加
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # ログレコードの extra 属性に追加情報を詰めた場合はそれを含める
        # 例: logger.info("message", extra={"user_id": 123})
        if hasattr(record, "client_ip"):
            log_obj["client_ip"] = record.client_ip
        if hasattr(record, "user_id"):
            log_obj["user_id"] = record.user_id
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id
        if hasattr(record, "duration_ms"):
            log_obj["duration_ms"] = record.duration_ms
        if hasattr(record, "status_code"):
            log_obj["status_code"] = record.status_code

        return json.dumps(log_obj, ensure_ascii=False)


class SimpleFormatter(logging.Formatter):
    """開発環境向けのシンプルなログフォーマッタ。

    人間にとって読みやすい形式でログを出力する。
    """

    def __init__(self) -> None:
        """初期化。フォーマット文字列を設定する。"""
        super().__init__(
            "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_logging() -> None:
    """ログシステムの初期化。

    環境変数 LOG_LEVEL（デフォルト INFO）と LOG_FORMAT（デフォルト simple）
    から設定を取得し、ロギングシステムを初期化する。

    LOG_FORMAT の値:
      - "simple": 開発環境向けのシンプルな形式
      - "json": 本番環境向けの JSON 形式

    環境変数の例:
      LOG_LEVEL=DEBUG LOG_FORMAT=json python main.py
    """
    # ログレベルを環境変数から取得（デフォルト: INFO）
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    # ログフォーマットを環境変数から取得（デフォルト: simple）
    log_format = os.getenv("LOG_FORMAT", "simple").lower()

    # ルートロガーの設定
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 既存のハンドラをクリア（重複登録防止）
    root_logger.handlers.clear()

    # 標準出力へのハンドラを作成
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # フォーマッタを設定
    if log_format == "json":
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = SimpleFormatter()

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """ロガーインスタンスを取得する。

    モジュール内でロガーを使う際は、通常 __name__ を渡してモジュール名を記録する。

    Args:
        name: ロガー名（通常は __name__）

    Returns:
        Logger インスタンス

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Application started")
    """
    return logging.getLogger(name)
