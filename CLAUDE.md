# CLAUDE.md
このプロジェクトでコードを書く際の指示。

## コーディング規約

- 関数・メソッドには必ず型ヒントをつける（引数・返り値の両方）
- docstringを書く際は引数（Args）と返り値（Returns / Yields）の説明を含める
- キリがいいところでコミットメッセージを提示すること
- 実際のコミットは自分が行うので、ブランチ作成などの提案は不要
- スクリプトを作成した場合は、勉強のためにもコメントを多めにつけて理解ができるようにしてください

## MCP サーバーの同梱ドキュメントの同期
- **DBスキーマ（`app/models.py` やテーブル定義、移行スクリプト）を変更したら、
  `app/mcp/knowledge/schema.md` の該当箇所も必ず更新する**（カラムの増減・型・md/four 差分・座標系など）
- 集計の定義や SQL 上の注意点が変わったら、`metrics.md` / `sql_notes.md` も併せて見直す
- 競技規則の変遷は `app/mcp/knowledge/rules/*.yaml` が唯一の情報源。YAML を変更したら
  `uv run python scripts/generate_rules_md.py` で `rules.md` を生成し直す（`rules.md` は直接編集しない。
  食い違いは `tests/test_rules_md.py` が検出する）。書き方と対象範囲は `rules/README.md` を参照
- スキーマの真は `app/models.py` 。knowledge 配下と食い違ったら
  実態（DB / models）を正とし、ドキュメントを合わせる
