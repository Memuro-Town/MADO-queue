# GitHub Traffic スナップショット

GitHub の Traffic API（`/traffic/clones`・`/traffic/views`）は**直近約14日分**しか返さない。
週1回 `.github/workflows/traffic-snapshot.yml` が日付キーでマージし、`traffic.json` に蓄積する。

- 手動実行: Actions → "Weekly traffic snapshot" → Run workflow
- 値の意味: `count` はその日の回数、`uniques` はその日のユニーク（期間ユニークではない）
