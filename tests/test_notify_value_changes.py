"""scripts/notify_update.py のうち、値の修正（件数が変わらない更新）を検出する処理のテスト。

小さな SQLite を2つ（修正前・修正後）作り、detect_value_changes が変化を見つけられるかを確かめる。

特に守りたいのは、「修正前は値が全部 NULL だった列に、値が入った」ケース。
以前は NULL を除いて集計し、前後の両方に値がある大会だけを比べていたため、
md_261018.db で WMDCC2016・WMDCC2017 のショットタイプが埋まったことを検出できなかった。

確認すること:
  1. 離散値（shots.type）: 全部 NULL → 値が入った、を検出する
  2. 連続値（stones.x）: 全部 NULL → 値が入った、を検出する
  3. 文字列（games.team_red）: 全部 NULL → 値が入った、を検出する
  4. 何も変わっていなければ、何も検出しない
  5. 片方にしかない大会（大会の追加）は、値の修正として扱わない
"""

import sqlite3
from pathlib import Path

from scripts import notify_update as nu

# 検出に必要な列だけを持つ、小さなスキーマ
SCHEMA = """
CREATE TABLE events (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE games (id INTEGER PRIMARY KEY, event_id INTEGER, team_red TEXT, team_yellow TEXT);
CREATE TABLE ends (id INTEGER PRIMARY KEY, game_id INTEGER);
CREATE TABLE shots (id INTEGER PRIMARY KEY, end_id INTEGER, type TEXT);
CREATE TABLE stones (id INTEGER PRIMARY KEY, shot_id INTEGER, x REAL);
"""


def make_db(
    path: Path,
    *,
    types: list[str | None],
    xs: list[float | None],
    team: str | None,
    extra_event: bool = False,
) -> str:
    """大会1つ（試合1・エンド1）だけを持つ SQLite を作る。

    Args:
        path:        作成するファイルのパス
        types:       shots.type の値（1要素が1投球）
        xs:          stones.x の値（1要素が1ストーン。すべて1投目に紐づける）
        team:        games.team_red / team_yellow の値
        extra_event: True なら、行を持たない大会 "NEW2026" も追加する（大会の追加を模す）

    Returns:
        str: 作成したファイルのパス
    """
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO events VALUES (1, 'WMDCC2016')")
    if extra_event:
        conn.execute("INSERT INTO events VALUES (2, 'NEW2026')")
    conn.execute("INSERT INTO games VALUES (1, 1, ?, ?)", (team, team))
    conn.execute("INSERT INTO ends VALUES (1, 1)")
    for i, t in enumerate(types, start=1):
        conn.execute("INSERT INTO shots VALUES (?, 1, ?)", (i, t))
    for i, x in enumerate(xs, start=1):
        conn.execute("INSERT INTO stones VALUES (?, 1, ?)", (i, x))
    conn.commit()
    conn.close()
    return str(path)


def changed_columns(prev: str, new: str) -> dict[str, list[str]]:
    """detect_value_changes の結果を {列: [大会名, ...]} にまとめる。

    Args:
        prev: 修正前の SQLite のパス
        new:  修正後の SQLite のパス

    Returns:
        dict[str, list[str]]: 変化が検出された列と、その大会名のリスト
    """
    return {
        r["col_key"]: [c["event"] for c in r["changes"]] for r in nu.detect_value_changes(prev, new)
    }


def test_detects_discrete_column_filled_from_all_null(tmp_path: Path) -> None:
    """shots.type が全部 NULL → 値が入った場合に検出することを確認する。"""
    # Arrange
    prev = make_db(tmp_path / "prev.db", types=[None, None], xs=[0.1], team="JPN")
    new = make_db(tmp_path / "new.db", types=["Draw", "Guard"], xs=[0.1], team="JPN")

    # Act
    result = nu.detect_value_changes(prev, new)

    # Assert: shots.type の変化として、NULL の減少と値の増加が両方載る
    type_change = next(r for r in result if r["col_key"] == "shots.type")
    diff = type_change["changes"][0]["diff"]
    assert diff["NULL"] == (2, 0)
    assert diff["Draw"] == (0, 1)
    assert diff["Guard"] == (0, 1)


def test_detects_continuous_column_filled_from_all_null(tmp_path: Path) -> None:
    """stones.x が全部 NULL → 値が入った場合に検出することを確認する。"""
    # Arrange
    prev = make_db(tmp_path / "prev.db", types=["Draw"], xs=[None, None], team="JPN")
    new = make_db(tmp_path / "new.db", types=["Draw"], xs=[0.5, -0.5], team="JPN")

    # Act
    result = nu.detect_value_changes(prev, new)

    # Assert: 修正前の統計量は None（値なし）、修正後は値あり
    x_change = next(r for r in result if r["col_key"] == "stones.x")
    change = x_change["changes"][0]
    assert change["event"] == "WMDCC2016"
    assert change["before"] is None
    assert change["after"]["min"] == -0.5


def test_detects_string_column_filled_from_all_null(tmp_path: Path) -> None:
    """games.team_red が全部 NULL → 値が入った場合に検出することを確認する。"""
    # Arrange
    prev = make_db(tmp_path / "prev.db", types=["Draw"], xs=[0.1], team=None)
    new = make_db(tmp_path / "new.db", types=["Draw"], xs=[0.1], team="JPN")

    # Act
    columns = changed_columns(prev, new)

    # Assert
    assert columns["games.team_red"] == ["WMDCC2016"]


def test_no_changes_when_identical(tmp_path: Path) -> None:
    """中身が同じなら何も検出しないことを確認する（NULL を含んでいても）。"""
    # Arrange
    kwargs = {"types": ["Draw", None], "xs": [0.1, None], "team": None}
    prev = make_db(tmp_path / "prev.db", **kwargs)
    new = make_db(tmp_path / "new.db", **kwargs)

    # Act & Assert
    assert nu.detect_value_changes(prev, new) == []


def test_added_event_is_not_reported_as_modification(tmp_path: Path) -> None:
    """片方にしかない大会（大会の追加）は、値の修正として扱わないことを確認する。"""
    # Arrange: 修正後にだけ大会 NEW2026 がある。既存の大会の中身は同じ
    prev = make_db(tmp_path / "prev.db", types=["Draw"], xs=[0.1], team="JPN")
    new = make_db(tmp_path / "new.db", types=["Draw"], xs=[0.1], team="JPN", extra_event=True)

    # Act & Assert
    assert nu.detect_value_changes(prev, new) == []
