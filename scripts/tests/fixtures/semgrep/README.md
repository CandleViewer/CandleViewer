# Semgrep JSON reports with parse gaps (#3549)

`test_security_gate.py` runs these through `tools/ci/security_gate.py --semgrep-json`. Semgrep's
SARIF lists a parse error as a notification with no line span and still reads as a complete scan,
so the gate reads the JSON report (`--json-output`) to find a file the engine did not analyse.
Recorded 2026-10-18 in this directory with `semgrep scan --metrics=off --config rules.yml --sarif
--output <scratch>.sarif --json-output semgrep-<version>.json skipped.py partial.py unparsed.py
drill.sh`, as written, then re-indented by prettier (lint-staged). `rules.yml` flags each `print`
call and `echo` command, so a missed one shows what Semgrep did not analyse. `.semgrepignore` keeps
the CI scan out of this directory: its sources do not parse on purpose.

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
