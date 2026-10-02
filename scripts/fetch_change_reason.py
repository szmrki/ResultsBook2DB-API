"""
scripts/fetch_change_reason.py

DB更新の「変更理由」を、生成元リポジトリ（ResultsBook2DB）の GitHub から取得するスクリプト。

notify_update.py の数値比較は「何が変わったか」しか分からない。
「なぜ変わったか」は生成元リポジトリのリリースノート・PR・issue に書かれているので、
リリースを起点に次の順で辿って集める。

    リリース（v1.4.1 など）
      └─ 本文に載っている PR（.../pull/25）
           └─ PR 本文の "Closes #24" が指す issue

このモジュールが知っているのは GitHub のことだけ。差分データ（SQLite）との突き合わせは
notify_update.py 側で行う。「どのバージョンを調べるか」を呼び出し元が決める作りにして
あるので、将来バージョンの出どころが変わっても（台帳DBなど）このファイルは変更不要。

ResultsBook2DB は公開リポジトリなので、認証なし（トークンなし）で読める。

使い方:
  # タグを指定して取得（結果を JSON で表示）
  PYTHONPATH=. uv run python scripts/fetch_change_reason.py v1.4.1

  # タグ省略時は最新リリースを取得
  PYTHONPATH=. uv run python scripts/fetch_change_reason.py
"""

import argparse
import json
import re

import requests

# 生成元リポジトリ（"オーナー/リポジトリ名" 形式）
SOURCE_REPO = "szmrki/ResultsBook2DB"

# GitHub REST API のベースURL
API_BASE = "https://api.github.com"

# HTTP タイムアウト（秒）。GitHub が応答しないときに通知全体を待たせないための上限。
TIMEOUT_SECONDS = 10

# 本文（リリースノート・PR・issue）を切り詰める上限文字数。
# Gemini のプロンプトに丸ごと渡すため、極端に長い本文で膨らまないようにする。
MAX_BODY_CHARS = 6000

# リリース本文から PR 番号を拾う正規表現。
# 自動生成のリリースノートは PR を
#   https://github.com/szmrki/ResultsBook2DB/pull/25
# という URL で載せるので、この形だけを対象にする。
# re.escape は "/" や "." などを「文字そのもの」として扱うためのエスケープ。
_PR_URL_PATTERN = re.compile(
    rf"https://github\.com/{re.escape(SOURCE_REPO)}/pull/(\d+)"
)

# PR 本文から「この PR が閉じる issue」の番号を拾う正規表現。
# GitHub は close / closes / closed / fix / fixes / fixed / resolve / resolves / resolved
# のいずれかに "#番号" が続く書き方を、issue を閉じるキーワードとして扱う。
#   close[sd]?    … close, closes, closed
#   fix(?:e[sd])? … fix, fixes, fixed
#   resolve[sd]?  … resolve, resolves, resolved
# \b は単語の境界。"prefix #1" のような単語の一部には反応させないために付ける。
_CLOSING_PATTERN = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
    re.IGNORECASE,  # "Closes" / "closes" など大文字小文字を区別しない
)


class ChangeReasonError(Exception):
    """変更理由の取得に失敗したことを表す例外。

    通信エラー・HTTP エラー・想定外の応答をまとめてこの例外にする。
    呼び出し側はこの1種類だけ捕まえれば「取得失敗 → 数値差分のみで通知」に
    フォールバックできる。
    """


# ─── GitHub API 呼び出し ──────────────────────────────────────────────────────


def _get_json(path: str) -> dict:
    """GitHub REST API に GET リクエストを送り、JSON を辞書で返す。

    Args:
        path: API のパス（例 "/repos/szmrki/ResultsBook2DB/releases/latest"）

    Returns:
        dict: レスポンスの JSON をパースした辞書

    Raises:
        ChangeReasonError: 通信エラー、200 以外のステータス、JSON でない応答の場合
    """
    url = f"{API_BASE}{path}"
    headers = {
        # GitHub が推奨する Accept ヘッダー（JSON 形式で返してもらう指定）
        "Accept": "application/vnd.github+json",
        # API のバージョンを固定する。将来 API の既定の挙動が変わっても影響を受けない。
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        # RequestException は接続失敗・タイムアウト・DNS 失敗などの親クラス。
        # "from e" を付けると、元の例外が原因として記録される（デバッグしやすい）。
        raise ChangeReasonError(f"GitHub への接続に失敗: {e}") from e

    if response.status_code != 200:
        # 404（タグが存在しない）や 403（レート制限）など
        raise ChangeReasonError(
            f"GitHub API がエラーを返しました: {response.status_code} {url}"
        )

    try:
        data = response.json()
    except ValueError as e:
        raise ChangeReasonError(f"GitHub API の応答が JSON ではありません: {url}") from e

    if not isinstance(data, dict):
        raise ChangeReasonError(f"GitHub API の応答が想定外の形式です: {url}")
    return data


def _truncate(text: str | None) -> str:
    """本文を上限文字数で切り詰める（None は空文字にする）。

    Args:
        text: 切り詰める文字列。GitHub は本文が空のとき None を返すことがある。

    Returns:
        str: MAX_BODY_CHARS 以内に収めた文字列
    """
    if not text:
        return ""
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[:MAX_BODY_CHARS] + "\n...（以下省略）"


# ─── 本文からの番号抽出 ───────────────────────────────────────────────────────


def extract_pr_numbers(release_body: str) -> list[int]:
    """リリース本文に載っている PR の番号を取り出す。

    Args:
        release_body: リリースノートの本文

    Returns:
        list[int]: PR 番号のリスト（出現順・重複なし）
    """
    numbers = [int(n) for n in _PR_URL_PATTERN.findall(release_body)]
    # dict.fromkeys は「順序を保ったまま重複を除く」定番の書き方
    return list(dict.fromkeys(numbers))


def extract_closing_issue_numbers(pr_body: str) -> list[int]:
    """PR 本文の "Closes #N" などから、その PR が閉じる issue の番号を取り出す。

    Args:
        pr_body: PR の本文

    Returns:
        list[int]: issue 番号のリスト（出現順・重複なし）
    """
    numbers = [int(n) for n in _CLOSING_PATTERN.findall(pr_body)]
    return list(dict.fromkeys(numbers))


# ─── リリース・PR・issue の取得 ───────────────────────────────────────────────


def fetch_release(tag: str | None = None) -> dict:
    """リリース情報を取得する。

    Args:
        tag: リリースのタグ名（例 "v1.4.1"）。None なら最新リリースを取得する。

    Returns:
        dict: tag / name / published_at / url / body を持つ辞書

    Raises:
        ChangeReasonError: 取得に失敗した場合（タグが存在しない場合を含む）
    """
    if tag is None:
        path = f"/repos/{SOURCE_REPO}/releases/latest"
    else:
        path = f"/repos/{SOURCE_REPO}/releases/tags/{tag}"
    data = _get_json(path)
    return {
        "tag": data.get("tag_name", ""),
        "name": data.get("name", ""),
        # 公開日時（ISO 8601 形式、例 "2026-10-01T04:06:30Z"）
        "published_at": data.get("published_at", ""),
        "url": data.get("html_url", ""),
        "body": _truncate(data.get("body")),
    }


def fetch_issue(number: int) -> dict:
    """issue を取得する。

    Args:
        number: issue 番号

    Returns:
        dict: number / title / url / body を持つ辞書

    Raises:
        ChangeReasonError: 取得に失敗した場合
    """
    data = _get_json(f"/repos/{SOURCE_REPO}/issues/{number}")
    return {
        "number": number,
        "title": data.get("title", ""),
        "url": data.get("html_url", ""),
        "body": _truncate(data.get("body")),
    }


def fetch_pull(number: int) -> dict:
    """PR と、その PR が閉じる issue をまとめて取得する。

    Args:
        number: PR 番号

    Returns:
        dict: number / title / url / body / issues を持つ辞書。
            issues は fetch_issue の返り値のリスト。

    Raises:
        ChangeReasonError: 取得に失敗した場合
    """
    data = _get_json(f"/repos/{SOURCE_REPO}/pulls/{number}")
    body = data.get("body") or ""
    # 番号の抽出は切り詰める前の本文で行う（"Closes #N" が末尾にあっても拾えるように）
    issues = [fetch_issue(n) for n in extract_closing_issue_numbers(body)]
    return {
        "number": number,
        "title": data.get("title", ""),
        "url": data.get("html_url", ""),
        "body": _truncate(body),
        "issues": issues,
    }


def fetch_change_reason(tag: str | None = None) -> dict:
    """リリースを起点に、PR と issue を辿って変更理由の材料を集める。

    Args:
        tag: リリースのタグ名（例 "v1.4.1"）。None なら最新リリースを使う。

    Returns:
        dict: 次の2つのキーを持つ辞書
            - release: fetch_release の返り値
            - pulls: fetch_pull の返り値のリスト（リリース本文に載っている PR）

    Raises:
        ChangeReasonError: 途中のいずれかの取得に失敗した場合
    """
    release = fetch_release(tag)
    pulls = [fetch_pull(n) for n in extract_pr_numbers(release["body"])]
    return {"release": release, "pulls": pulls}


# ─── エントリーポイント ───────────────────────────────────────────────────────


def main() -> None:
    """引数のタグ（省略時は最新リリース）の変更理由を取得して JSON で表示する。"""
    parser = argparse.ArgumentParser(
        description="生成元リポジトリのリリースから変更理由（PR・issue）を取得する"
    )
    parser.add_argument(
        "tag", nargs="?", default=None,
        help="リリースのタグ名（例 v1.4.1）。省略時は最新リリース",
    )
    args = parser.parse_args()

    try:
        reason = fetch_change_reason(args.tag)
    except ChangeReasonError as e:
        print(f"エラー: {e}")
        raise SystemExit(1) from e

    print(json.dumps(reason, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
