"""scripts/notify_update.py の call_gemini が、一時的なエラーを再試行することのテスト。

Gemini は混雑時に 503（UNAVAILABLE）を返すことがある。本物の API では 503 を
狙って起こせないので、このテストでは 503 を返す偽の HTTP サーバーをローカルに立て、
SDK の接続先をそこに向けて、実際に HTTP リクエストが再送されることを確かめる。

確認すること:
  1. 503 が続いたあと成功すれば、通知文が返る（503 の回数 + 1 回リクエストが飛ぶ）
  2. 503 が最後まで続けば、設定した試行回数で打ち切って例外になる
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from google.genai import errors

from scripts import notify_update as nu

# 成功時に偽サーバーが返す応答（Gemini の generateContent の応答と同じ形）
SUCCESS_BODY = {
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"text": "生成された通知文"}]},
            "finishReason": "STOP",
        }
    ]
}

# 混雑時に Gemini が返す 503 の応答
UNAVAILABLE_BODY = {
    "error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}
}


class FakeGemini:
    """最初の数回だけ 503 を返し、その後は成功を返す偽の Gemini サーバー。"""

    def __init__(self, failures: int) -> None:
        """サーバーを空きポートで用意する（起動は start で行う）。

        Args:
            failures: 503 を返す回数。この回数を超えたリクエストには成功を返す。
        """
        self.failures = failures
        self.request_count = 0  # 受け取ったリクエストの数
        fake = self

        class Handler(BaseHTTPRequestHandler):
            """POST を受けて、回数に応じて 503 か 200 を返すハンドラ。"""

            def do_POST(self) -> None:  # メソッド名は http.server の決まり
                """リクエストを数え、failures 回目までは 503、それ以降は 200 を返す。"""
                fake.request_count += 1
                # リクエスト本文を読み捨てる（読まないと接続が正しく閉じない）
                self.rfile.read(int(self.headers.get("Content-Length", 0)))

                if fake.request_count <= fake.failures:
                    status, body = 503, UNAVAILABLE_BODY
                else:
                    status, body = 200, SUCCESS_BODY
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: object) -> None:
                """アクセスログを出さない（テスト出力を汚さないため）。"""

        # ポート 0 を指定すると、OS が空いているポートを自動で割り当てる
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def start(self) -> None:
        """別スレッドでサーバーを動かす（テスト本体と並行して応答するため）。"""
        # daemon=True にすると、テストが終わればスレッドも一緒に終了する
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        """サーバーを止めてポートを解放する。"""
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_gemini(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGemini]:
    """call_gemini の接続先を偽サーバーに向け、待ち時間を短くする。

    Args:
        monkeypatch: pytest 組み込みのフィクスチャ。テスト中だけ値を差し替える。

    Yields:
        FakeGemini: 偽サーバー。テスト側で failures を設定し、request_count を検証する。
    """
    fake = FakeGemini(failures=0)
    fake.start()

    # API キーが無いと call_gemini は接続前に例外を出すので、ダミーを設定する
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    # 本番の設定は数十秒待つので、待ち時間だけ短くする（試行回数は本番のまま）。
    # model_copy(update=...) は、指定した項目だけ差し替えたコピーを作る。
    fast_retry = nu.GEMINI_RETRY_OPTIONS.model_copy(
        update={"initial_delay": 0.01, "max_delay": 0.01, "jitter": 0.01}
    )
    monkeypatch.setattr(nu, "GEMINI_RETRY_OPTIONS", fast_retry)

    # genai.Client を、接続先（base_url）だけ偽サーバーに書き換えるものに差し替える。
    # リトライ設定などは call_gemini が渡したものをそのまま使う。
    real_client = nu.genai.Client

    def client_for_fake_server(**kwargs: object) -> object:
        """call_gemini が渡した引数の base_url だけを書き換えて本物の Client を作る。"""
        kwargs["http_options"].base_url = fake.url  # type: ignore[attr-defined]
        return real_client(**kwargs)

    monkeypatch.setattr(nu.genai, "Client", client_for_fake_server)

    yield fake  # ここでテスト本体が実行される
    fake.stop()  # テストが終わったら（失敗しても）サーバーを止める


def test_retries_after_503_and_returns_text(fake_gemini: FakeGemini) -> None:
    """503 が2回続いても、3回目で成功すれば通知文が返る。"""
    fake_gemini.failures = 2

    message = nu.call_gemini("プロンプト")

    assert message == "生成された通知文"
    assert fake_gemini.request_count == 3  # 503 ×2 + 成功 ×1


def test_gives_up_after_configured_attempts(fake_gemini: FakeGemini) -> None:
    """503 が続く場合は、設定した試行回数で打ち切って例外になる。"""
    fake_gemini.failures = 999  # 常に 503

    with pytest.raises(errors.ServerError):
        nu.call_gemini("プロンプト")

    assert fake_gemini.request_count == nu.GEMINI_RETRY_OPTIONS.attempts
