# Real scanner SARIF (#3337, #3372)

`test_security_gate.py::test_real_scanner_sarif_still_parses` runs each file through
`tools/ci/security_gate.py`. Each scanner writes one run with a named `tool.driver` and a `results`
list, on a clean scan too, which is why the gate fails a SARIF without them (CI-SEC-005). The files
are compact JSON (`json.dumps(separators=(",", ":"))` and LF) with keys in the order their source
wrote them. Recorded 2026-10-18.

- `codeql-2.27.2-clean.sarif`: GitHub code scanning's copy of CodeQL 2.27.2 analysis 1974630613
  (PR #3338, no results), from `gh api` with `Accept: application/sarif+json` on
  `repos/basiltt/CandleViewer/code-scanning/analyses/1974630613`. Each query pack keeps only its
  first rule with a `security-severity`, without `help`.
- `codeql-2.27.2-analyze-clean.sarif`: what the codeql job gates, as `analyze` writes it, with the
  `invocations` that code scanning's copies drop (#3372): the `javascript.sarif` of CodeQL
  2.27.2's `analyze` in github/codeql-action's `__diagnostics-export.yml` run 39099201493 (no
  results), from its artifact `diagnostics-export-ubuntu-latest-linked.sarif.json`. Its invocation
  reports `executionSuccessful: true` and only `toolExecutionNotifications`. Trimmed: the query
  pack keeps its first rule with a `security-severity`, without `help`; each notification list and
  `artifacts` keep their first entry; the run's `properties` are dropped.
- `trivy-0.70.0-clean.sarif`: the same API for Trivy 0.70.0 analysis 1974683379 (PR #3288, no
  results), as served. Trivy writes no `invocations`.
- `semgrep-1.178.0-clean.sarif`: `semgrep scan --metrics=off --sarif` with the rule
  `.semgrep/cv-obs-no-print.yml` over `services/api/candleviewer/__init__.py`, as written.
- `semgrep-1.178.0-finding.sarif`: the same rule over `.semgrep/tests/cv-obs-no-print.py`, whose
  line 5 is a `# ruleid:` line, as written.
- `bandit-1.9.4-clean.sarif`: `bandit -r clean -f sarif -ll` over `clean/arith.py`, a two-line
  function with no call.
- `bandit-1.9.4-finding.sarif`: the same over `finding/parse_expr.py`, whose line 2 is
  `return eval(expr)` (B307).
- `bandit-1.9.4-skipped.sarif`: the same over `skipped/`, a two-line `arith.py` with no call and
  `broken.py`, whose first line `def broken(:` does not parse. Bandit exits 0, reports
  `executionSuccessful: true` and lists `broken.py` in an error-level
  `toolConfigurationNotifications` entry, so the gate fails it (#3372).

Bandit 1.9.4, not CI's 1.8.6: the only local Python is 3.14, where the 1.8.6 plugins fail
(`ast.Num` is gone). The two versions' `bandit/formatters/sarif.py` differ only in how they read
the clock for `endTimeUtc`.
