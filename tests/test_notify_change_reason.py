"""scripts/notify_update.py のうち、変更理由まわりの処理のテスト。

SQLite も Gemini も Slack も使わない純粋なロジックだけを対象にする。
GitHub からの取得（fetch_change_reason）は偽物に差し替える。

確認すること:
  1. 更新の種類（大会の追加 / 既存データの修正）を正しく判定する
  2. タグ指定・自動推定・取得失敗のそれぞれで、変更理由の扱いが決まる
  3. 変更理由の記述と実際の差分を、大会名で照合できる
  4. 取得に失敗しても、通知の定型部分とプロンプトは数値差分だけで組み立てられる
"""

import os
from pathlib import Path

import pytest

from scripts import notify_update as nu
from scripts.fetch_change_reason import ChangeReasonError

# 変更理由のサンプル（fetch_change_reason の返り値と同じ構造）
REASON: dict = {
    "release": {
        "tag": "v1.4.1",
        "name": "Release v1.4.1",
        "published_at": "2026-10-01T04:06:30Z",
        "url": "https://example.com/releases/v1.4.1",
        "body": "fix: 反転判定を修正",
    },
    "pulls": [
        {
            "number": 25,
            "title": "fix: 反転判定を修正",
            "url": "https://example.com/pull/25",
            "body": "影響: WJCC2026 男女、PCCC2025Men。取りこぼしのない大会: WMCC2023",
            "issues": [
                {
                    "number": 24,
                    "title": "反転判定が失敗する",
                    "url": "https://example.com/issues/24",
                    "body": "内訳: PCCC2025Men 13 / WMCC2024 3",
                }
            ],
        }
    ],
}


def make_diff(changed_events: list[str]) -> dict:
    """指定した大会で値の修正が検出された、という差分情報を作る。

    Args:
        changed_events: 値の修正を検出したことにする大会名のリスト

    Returns:
        dict: detect_diff の返り値と同じ構造の辞書（テストに必要な部分のみ）
    """
    value_changes = []
    if changed_events:
        value_changes.append({
            "col_key": "stones.inhouse",
            "kind": "discrete",
            "changes": [{"event": name, "diff": {"0": (10, 9)}} for name in changed_events],
            "sort_score": 1.0,
        })
    return {
        "target": "four",
        "update_type": {"has_addition": False, "has_modification": bool(changed_events)},
        "schema_changes": {},
        "data_changes": {},
        "value_changes": value_changes,
    }


# ── 更新の種類の判定 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data_changes", "value_changes", "expected"),
    [
        # 新しい大会が増えただけ → 追加のみ（変更理由は取得しない）
        (
            {"events": {"diff": 1, "added_names": ["WMCC2027"]}, "games": {"diff": 100}},
            [],
            {"has_addition": True, "has_modification": False},
        ),
        # 件数は同じで既存の値が変わった → 修正のみ（v1.4.1 の更新がこの形）
        (
            {"events": {"diff": 0, "added_names": []}, "stones": {"diff": 0}},
            [{"col_key": "stones.x"}],
            {"has_addition": False, "has_modification": True},
        ),
        # 大会の追加と既存の値の変化が同時 → 両方
        (
            {"events": {"diff": 1, "added_names": ["WMCC2027"]}},
            [{"col_key": "stones.x"}],
            {"has_addition": True, "has_modification": True},
        ),
        # 件数が減った → 既存の行が消えているので修正
        (
            {"events": {"diff": 0, "added_names": []}, "stones": {"diff": -5}},
            [],
            {"has_addition": False, "has_modification": True},
        ),
        # 新しい大会が無いのに件数が増えた → 既存の大会に行が足されたので修正
        (
            {"events": {"diff": 0, "added_names": []}, "stones": {"diff": 5}},
            [],
            {"has_addition": False, "has_modification": True},
        ),
        # 何も変わっていない
        (
            {"events": {"diff": 0, "added_names": []}},
            [],
            {"has_addition": False, "has_modification": False},
        ),
    ],
)
def test_classify_update(
    data_changes: dict, value_changes: list[dict], expected: dict[str, bool]
) -> None:
    """件数の変化と値の変化から、追加・修正を判定する。"""
    assert nu.classify_update(data_changes, value_changes) == expected


# ── 変更理由の解決（タグ指定 / 自動推定 / 失敗） ───────────────────────


@pytest.fixture
def db_files(tmp_path: Path) -> tuple[str, str]:
    """更新日時だけが意味を持つ、空の prev / new ファイルを作る。

    prev は 2026-07-15、new は 2026-10-03 の更新日時にする。
    サンプルのリリース公開日（2026-10-01）がこの間に入る。

    Args:
        tmp_path: pytest 組み込みのフィクスチャ。テストごとの一時ディレクトリ。

    Returns:
        tuple[str, str]: (prev ファイルのパス, new ファイルのパス)
    """
    prev_file = tmp_path / "prev.db"
    new_file = tmp_path / "new.db"
    prev_file.touch()
    new_file.touch()
    # os.utime でファイルの更新日時を書き換える（引数は (アクセス日時, 更新日時) の秒数）
    prev_time = nu.datetime(2026, 7, 15, tzinfo=nu.timezone.utc).timestamp()
    new_time = nu.datetime(2026, 10, 3, tzinfo=nu.timezone.utc).timestamp()
    os.utime(prev_file, (prev_time, prev_time))
    os.utime(new_file, (new_time, new_time))
    return str(prev_file), str(new_file)


def test_resolve_with_explicit_tag(
    db_files: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """タグを指定した場合は、そのリリースをそのまま採用する。"""
    requested: list[str | None] = []

    def fake_fetch(tag: str | None = None) -> dict:
        """要求されたタグを記録して、サンプルの変更理由を返す。"""
        requested.append(tag)
        return REASON

    monkeypatch.setattr(nu, "fetch_change_reason", fake_fetch)

    resolution = nu.resolve_change_reason("v1.4.1", *db_files)

    assert requested == ["v1.4.1"]
    assert resolution["status"] == "found"
    assert resolution["reason"] is REASON


def test_resolve_auto_accepts_release_in_update_window(
    db_files: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """タグ省略時、最新リリースの公開日が更新期間に入っていれば採用する。"""
    monkeypatch.setattr(nu, "fetch_change_reason", lambda tag=None: REASON)

    resolution = nu.resolve_change_reason(None, *db_files)

    assert resolution["status"] == "found"


def test_resolve_auto_rejects_release_outside_update_window(
    db_files: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """タグ省略時、最新リリースが前回の更新より古ければ「特定できない」とする。

    前回の更新以降にリリースが出ていない（コードは変わっていない）状況で、
    古いリリースを今回の変更理由として通知してしまうのを防ぐ。
    """
    old_release = {**REASON["release"], "published_at": "2026-07-14T08:13:02Z"}
    old_reason = {**REASON, "release": old_release}
    monkeypatch.setattr(nu, "fetch_change_reason", lambda tag=None: old_reason)

    resolution = nu.resolve_change_reason(None, *db_files)

    assert resolution["status"] == "unknown"
    assert resolution["reason"] is None
    assert "v1.4.1" in resolution["note"]


def test_resolve_returns_failed_when_fetch_fails(
    db_files: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub から取得できなくても例外は出さず、failed として返す。"""

    def failing_fetch(tag: str | None = None) -> dict:
        """常に取得失敗の例外を出す偽の fetch_change_reason。"""
        raise ChangeReasonError("GitHub への接続に失敗")

    monkeypatch.setattr(nu, "fetch_change_reason", failing_fetch)

    resolution = nu.resolve_change_reason("v1.4.1", *db_files)

    assert resolution["status"] == "failed"
    assert resolution["reason"] is None
    assert "接続に失敗" in resolution["note"]


# ── 大会名の言及の検出 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "event_names", "expected"),
    [
        # そのままの名前
        ("影響: PCCC2025Men と WMCC2024", {"PCCC2025Men", "WMCC2024"}, {"PCCC2025Men", "WMCC2024"}),
        # 「男女」とまとめた書き方は Men / Women の両方（空白の有無を問わない）
        ("WJCC2026 男女", {"WJCC2026Men", "WJCC2026Women"}, {"WJCC2026Men", "WJCC2026Women"}),
        ("WJCC2026男女", {"WJCC2026Men", "WJCC2026Women"}, {"WJCC2026Men", "WJCC2026Women"}),
        # 片方だけ書かれていれば片方だけ
        ("PCCC2025Men のみ", {"PCCC2025Men", "PCCC2025Women"}, {"PCCC2025Men"}),
        # md の大会名は "MD" 付きでも、空白を挟んでも拾う
        ("OQE2025MD と OWG2026 MD", {"OQE2025", "OWG2026"}, {"OQE2025", "OWG2026"}),
        # 4人制の "OWG2026Men" を、md の大会 "OWG2026" への言及とは扱わない
        ("OWG2026Men", {"OWG2026"}, set()),
        # 別の名前の一部になっているものは拾わない
        ("XWMCC2024 / WMCC20245", {"WMCC2024"}, set()),
    ],
)
def test_find_mentioned_events(text: str, event_names: set[str], expected: set[str]) -> None:
    """テキスト中の大会名を、表記のゆれを吸収して検出する。"""
    assert nu.find_mentioned_events(text, event_names) == expected


# ── 変更理由と差分の照合 ───────────────────────────────────────────────

# DB に存在する大会名（照合の母集団）
EVENT_NAMES = {
    "WJCC2026Men", "WJCC2026Women", "PCCC2025Men", "WMCC2024", "WMCC2023", "ECC2022Men",
}


def test_consistency_when_all_changes_are_explained() -> None:
    """修正を検出した大会がすべて変更理由に載っていれば、説明のつかない大会は無い。"""
    diff = make_diff(["WJCC2026Men", "WJCC2026Women", "PCCC2025Men", "WMCC2024"])

    consistency = nu.check_reason_consistency(diff, REASON, EVENT_NAMES)

    assert consistency["unexplained_events"] == []
    # 「取りこぼしのない大会」として書かれた WMCC2023 は、言及のみ・変化なしに入る
    assert consistency["mentioned_unchanged_events"] == ["WMCC2023"]


def test_consistency_detects_unexplained_change() -> None:
    """変更理由に載っていない大会の変化は、説明のつかない変化として検出する。"""
    diff = make_diff(["PCCC2025Men", "ECC2022Men"])

    consistency = nu.check_reason_consistency(diff, REASON, EVENT_NAMES)

    assert consistency["changed_events"] == ["ECC2022Men", "PCCC2025Men"]
    assert consistency["unexplained_events"] == ["ECC2022Men"]


# ── 通知の定型部分 ─────────────────────────────────────────────────────


def test_footer_with_reason_lists_events_without_urls() -> None:
    """変更理由がある場合も、載せるのは影響大会だけ（リリースや issue の URL は載せない）。"""
    diff = make_diff(["PCCC2025Men", "WMCC2024"])
    resolution = {"status": "found", "reason": REASON, "note": ""}
    consistency = nu.check_reason_consistency(diff, REASON, EVENT_NAMES)

    footer = nu.build_reason_footer(diff, resolution, consistency)

    assert "既存データの修正を検出した大会（2）" in footer
    assert "PCCC2025Men, WMCC2024" in footer
    assert "http" not in footer
    assert "⚠" not in footer  # 説明のつかない変化が無ければ警告は出さない


def test_footer_warns_about_unexplained_events() -> None:
    """説明のつかない変化がある場合、その大会名を警告として載せる。"""
    diff = make_diff(["PCCC2025Men", "ECC2022Men"])
    resolution = {"status": "found", "reason": REASON, "note": ""}
    consistency = nu.check_reason_consistency(diff, REASON, EVENT_NAMES)

    footer = nu.build_reason_footer(diff, resolution, consistency)

    assert "⚠ 変更理由に記載の無い大会でも値の変化を検出しました: ECC2022Men" in footer


def test_footer_states_reason_is_unknown() -> None:
    """自動推定できなかった場合、変更理由が不明であることを明記する。"""
    diff = make_diff(["PCCC2025Men"])
    resolution = {"status": "unknown", "reason": None, "note": "更新期間の外です"}

    footer = nu.build_reason_footer(diff, resolution, None)

    assert "変更理由は自動では特定できませんでした（更新期間の外です）" in footer


def test_footer_falls_back_to_events_only_when_fetch_failed() -> None:
    """取得に失敗した場合は、数値差分から分かること（影響大会）だけを載せる。"""
    diff = make_diff(["PCCC2025Men"])
    resolution = {"status": "failed", "reason": None, "note": "GitHub への接続に失敗"}

    footer = nu.build_reason_footer(diff, resolution, None)

    assert "PCCC2025Men" in footer
    assert "変更理由" not in footer


def test_footer_is_empty_for_addition_only_update() -> None:
    """大会の追加だけの更新では、定型部分は付かない。"""
    assert nu.build_reason_footer(make_diff([]), None, None) == ""


# ── プロンプト ─────────────────────────────────────────────────────────


def test_prompt_includes_reason_material_only_when_given() -> None:
    """変更理由があるときだけ、資料と理由の書き方の要件がプロンプトに入る。"""
    diff = make_diff(["PCCC2025Men"])

    without_reason = nu.build_prompt(diff)
    with_reason = nu.build_prompt(diff, REASON)

    assert "変更理由の資料" not in without_reason
    assert "300文字以内" in without_reason

    assert "変更理由の資料" in with_reason
    assert "issue #24: 反転判定が失敗する" in with_reason
    assert "500文字以内" in with_reason
