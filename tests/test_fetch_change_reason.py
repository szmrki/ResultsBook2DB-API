"""scripts/fetch_change_reason.py（生成元リポジトリからの変更理由の取得）のテスト。

実際の GitHub には接続しない。requests.get を差し替え（monkeypatch）て、
決まった応答を返す偽物に置き換えることで、ネットワーク無しで検証する。

確認すること:
  1. リリース本文から PR 番号を、PR 本文から閉じる issue の番号を取り出せる
  2. リリース → PR → issue と辿って、変更理由をひとまとめにできる
  3. 通信エラー・HTTP エラーは ChangeReasonError になる
"""

import pytest
import requests

from scripts import fetch_change_reason as fcr


class FakeResponse:
    """requests.Response の代役。テストに必要な status_code と json() だけ持つ。"""

    def __init__(self, status_code: int, payload: dict) -> None:
        """応答のステータスコードと JSON の中身を受け取る。

        Args:
            status_code: HTTP ステータスコード
            payload: json() が返す辞書
        """
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        """応答の JSON を辞書で返す。

        Returns:
            dict: コンストラクタで受け取った payload
        """
        return self._payload


# GitHub API の応答を模したデータ（URL の末尾 → 応答の中身）。
# 実際の v1.4.1 と同じ構造: リリースに PR が2つ載り、片方の PR だけが issue を閉じる。
FAKE_API: dict[str, dict] = {
    "/releases/tags/v1.4.1": {
        "tag_name": "v1.4.1",
        "name": "Release v1.4.1",
        "published_at": "2026-10-01T04:06:30Z",
        "html_url": "https://github.com/szmrki/ResultsBook2DB/releases/tag/v1.4.1",
        "body": (
            "* test: スクリプトを追加 in https://github.com/szmrki/ResultsBook2DB/pull/23\n"
            "* fix: 反転判定を修正 in https://github.com/szmrki/ResultsBook2DB/pull/25\n"
        ),
    },
    "/pulls/23": {
        "title": "test: スクリプトを追加",
        "html_url": "https://github.com/szmrki/ResultsBook2DB/pull/23",
        "body": "テスト用のスクリプトを追加した。",
    },
    "/pulls/25": {
        "title": "fix: 反転判定を修正",
        "html_url": "https://github.com/szmrki/ResultsBook2DB/pull/25",
        "body": "反転の取りこぼしをなくす。\n\nCloses #24\n",
    },
    "/issues/24": {
        "title": "反転判定が失敗する",
        "html_url": "https://github.com/szmrki/ResultsBook2DB/issues/24",
        "body": "375枚で取りこぼしが見つかった。",
    },
}


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """requests.get を FAKE_API の応答を返す偽物に差し替える。

    Args:
        monkeypatch: pytest 組み込みのフィクスチャ。テスト中だけ属性を差し替え、
            テストが終わると自動で元に戻す。

    Returns:
        list[str]: 呼び出された URL の記録（どの API を叩いたかの検証に使う）
    """
    called_urls: list[str] = []

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        """URL の末尾が FAKE_API のキーに一致すればその応答を、無ければ 404 を返す。"""
        called_urls.append(url)
        for suffix, payload in FAKE_API.items():
            if url.endswith(suffix):
                return FakeResponse(200, payload)
        return FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr(fcr.requests, "get", fake_get)
    return called_urls


# ── 本文からの番号抽出 ─────────────────────────────────────────────────


def test_extract_pr_numbers_from_release_body() -> None:
    """リリース本文の PR の URL から番号を取り出す（重複は除き、他リポジトリは無視）。"""
    body = (
        "* a in https://github.com/szmrki/ResultsBook2DB/pull/23\n"
        "* b in https://github.com/szmrki/ResultsBook2DB/pull/25\n"
        "* 再掲 https://github.com/szmrki/ResultsBook2DB/pull/23\n"
        "* 別リポジトリ https://github.com/szmrki/ResultsBook2DB-API/pull/99\n"
        "**Full Changelog**: https://github.com/szmrki/ResultsBook2DB/compare/v1.4.0...v1.4.1\n"
    )
    assert fcr.extract_pr_numbers(body) == [23, 25]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Closes #24", [24]),
        ("closes #24 and fixes #7", [24, 7]),  # 大文字小文字を問わず、複数拾う
        ("Resolved #3\nFixed #3", [3]),  # 重複は1つにまとめる
        ("#20 と関連する", []),  # キーワードが無い単なる参照は拾わない
        ("fix: 盤面の図を修正", []),  # コミット種別の "fix:" は対象外
        ("", []),
    ],
)
def test_extract_closing_issue_numbers(body: str, expected: list[int]) -> None:
    """PR 本文から「閉じる issue」の番号だけを取り出す。"""
    assert fcr.extract_closing_issue_numbers(body) == expected


# ── リリース → PR → issue の取得 ───────────────────────────────────────


def test_fetch_change_reason_follows_release_to_issue(fake_github: list[str]) -> None:
    """リリースに載っている PR と、PR が閉じる issue まで辿って取得する。"""
    reason = fcr.fetch_change_reason("v1.4.1")

    assert reason["release"]["tag"] == "v1.4.1"
    assert reason["release"]["published_at"] == "2026-10-01T04:06:30Z"

    # PR は2つ。issue を閉じるのは #25 だけ。
    assert [pull["number"] for pull in reason["pulls"]] == [23, 25]
    assert reason["pulls"][0]["issues"] == []
    assert [issue["number"] for issue in reason["pulls"][1]["issues"]] == [24]
    assert reason["pulls"][1]["issues"][0]["title"] == "反転判定が失敗する"


def test_fetch_release_without_tag_uses_latest(
    fake_github: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """タグを省略すると最新リリースの API を呼ぶ。"""
    # setitem は辞書の要素をテスト中だけ追加し、終わると元に戻す
    monkeypatch.setitem(FAKE_API, "/releases/latest", FAKE_API["/releases/tags/v1.4.1"])

    release = fcr.fetch_release()

    assert release["tag"] == "v1.4.1"
    assert fake_github[-1].endswith("/releases/latest")


def test_long_body_is_truncated(
    fake_github: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """上限を超える本文は切り詰められる（プロンプトの肥大化を防ぐ）。"""
    long_issue = {**FAKE_API["/issues/24"], "body": "あ" * (fcr.MAX_BODY_CHARS + 100)}
    monkeypatch.setitem(FAKE_API, "/issues/24", long_issue)

    issue = fcr.fetch_issue(24)

    assert issue["body"].startswith("あ" * fcr.MAX_BODY_CHARS)
    assert issue["body"].endswith("（以下省略）")


# ── 異常系 ─────────────────────────────────────────────────────────────


def test_unknown_tag_raises(fake_github: list[str]) -> None:
    """存在しないタグ（404）は ChangeReasonError になる。"""
    with pytest.raises(fcr.ChangeReasonError):
        fcr.fetch_change_reason("v9.9.9")


def test_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """接続失敗などの通信エラーは ChangeReasonError に包まれる。"""

    def raise_connection_error(url: str, **kwargs: object) -> FakeResponse:
        """常に接続エラーを起こす偽の requests.get。"""
        raise requests.ConnectionError("ネットワークに接続できません")

    monkeypatch.setattr(fcr.requests, "get", raise_connection_error)

    with pytest.raises(fcr.ChangeReasonError):
        fcr.fetch_change_reason("v1.4.1")
