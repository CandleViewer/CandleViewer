YAML Semgrep rule-test fixtures live outside `.semgrep/` (Semgrep recurses config dirs and would parse them as rule files), so `semgrep --config .semgrep` validates.
