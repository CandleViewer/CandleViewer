# Semgrep JSON reports with parse gaps (#3549)

`test_security_gate.py` runs these through `tools/ci/security_gate.py --semgrep-json`. Semgrep's
SARIF lists a parse error as a notification with no line span and still reads as a complete scan,
so the gate reads the JSON report (`--json-output`) to find a target a rule did not analyse.
Recorded 2026-10-18 in this directory with `semgrep scan --metrics=off --verbose --config
rules.yml --sarif --output <scratch>.sarif --json-output semgrep-<version>.json skipped.py
partial.py unparsed.py drill.sh`, as written, then re-indented by prettier (lint-staged).
`--verbose`, which CI passes too, adds `paths.skipped`: here each file with an error, as
`analysis_failed_parser_or_internal_error`; without the flag the reports are the same otherwise.
`rules.yml` flags each `print` call and `echo` command, in a workflow's `run:` script too, so a
missed one shows what Semgrep did not analyse. `.semgrepignore` keeps the CI scan out of this
directory: its sources do not parse on purpose.

- `skipped.py`: a PEP 695 generic function after a `print` call. Semgrep 1.99.0, CI's pin before
  #3549, reports one `PartialParsing` error whose spans cover every code line, and misses the
  `print` on line 5, which comes before the generic.
- `partial.py`: a PEP 695 `type` alias. Semgrep 1.99.0 skips line 3 only and still finds the
  `print` on line 10.
- `unparsed.py`: a raw f-string with a replacement field and a PEP 695 generic class. Semgrep
  1.181.0, the pin since #3549, reports a `Syntax error` with no span: neither of its parsers
  reads the file, and the `print` on line 16 is missed.
- `drill.sh`: a one-line `case` statement after two comment lines. Both versions report a
  `PartialParsing` error over lines 3 to 5, every code line, and miss both `echo` commands.
- `semgrep-1.99.0.json`: Semgrep 1.99.0 over the four files. It ran on CPython 3.14 with
  protobuf's pure-Python backend (its upb extension does not load on 3.14); the parser is the
  bundled `semgrep-core` binary that CI's CPython 3.12 runs too.
- `semgrep-1.181.0.json`: Semgrep 1.181.0 over the four files.

`semgrep-1.181.0-rule-gaps.json` was recorded in a copy of this directory, twice with the same
result, with `semgrep scan --metrics=off --verbose --timeout 1 --config timeouts.yml --config
rules.yml --sarif --output <scratch>.sarif --json-output semgrep-1.181.0-rule-gaps.json slow.py
many.py workflow.yml`. It holds no finding at all:

- `slow.py`: the three `timeouts.yml` rules time out on it, and then Semgrep runs no other rule
  there (its default `--timeout-threshold` is 3): with `--timeout-threshold 0`, `python-print`
  finds line 68. Timeouts depend on the machine; on a faster one, add assignments.
- `many.py`: too many matches. Semgrep names one rule, `slow-sequence-a`, and drops every rule's
  findings on the file; `rules.yml` alone finds the `print` on line 28.
- `workflow.yml`: `workflow-run-echo` cannot parse the one-line `case` in the `run:` script as
  Bash and reports lines 7 to 9; the YAML itself parsed. With the `case` on three lines the rule
  matches the script, on line 7.

`semgrep-1.181.0-skips.json` was recorded in a directory holding copies of `partial.py`,
`slow.py`, `unparsed.py` and `workflow.yml`, with `rules.yml` and `newer.yml` one level up, by
`semgrep scan --metrics=off --verbose --max-target-bytes 500 --exclude unparsed.py --config
../rules.yml --config ../newer.yml --sarif --output ../<scratch>.sarif --json-output
../semgrep-1.181.0-skips.json .`, twice with the same result. It walks the directory: Semgrep
applies the size limit only to the targets it finds, not to the ones it is given. Only
`paths.skipped` and `errors` show the gaps:

- `slow.py` (845 bytes) is over the 500-byte limit: `exceeded_size_limit`, with no error.
- `unparsed.py` is excluded on the command line: `cli_exclude_flags_match`.
- `newer-semgrep-only` (`newer.yml`) needs Semgrep 99.0.0, so it never runs: an
  `IncompatibleRule` error, and `newer.yml` listed as `analysis_failed_parser_or_internal_error`.
  1.181.0 writes `skipped_rules` as an empty list whatever it skips.
- `workflow.yml`: the YAML snippet gap of `semgrep-1.181.0-rule-gaps.json`, so it is also listed
  as `analysis_failed_parser_or_internal_error`. `partial.py`'s `print` on line 10 is found.
