# Real `pnpm audit --json` reports (#3494)

`test_security_gate.py` runs each file through `tools/ci/security_gate.py --tool npm-audit`, the
gate on the `npm-audit` step of `_job-security.yml`'s `read-only-scans` job. That step runs
`pnpm audit --json`, and pnpm's report is not npm's: an `advisories` object keyed by npm's
numeric advisory id (each entry is one GHSA advisory on one module, with a `findings` list of the
installed vulnerable versions and their dependency paths) and a `metadata` object whose
`vulnerabilities` counts those advisories per severity (`info`, `low`, `moderate`, `high`,
`critical`). Recorded 2026-10-18 with pnpm 12.5.1 (the `packageManager` pin) on Node 22.14.0,
against the public npm registry. pnpm writes `JSON.stringify(report, null, 2)` and a newline;
`.prettierignore` keeps the files that way.

- `pnpm-12.5.1-main.json`: the repository at `main` d77138f07. 11 advisories: 2 Critical
  (tinypool 1.1.1), 2 High (source-map-js 1.2.1; braces 3.0.3, accepted as EX-06),
  6 Moderate and 1 Low. Trimmed: each `findings` entry keeps its first two `paths` (source-map-js
  had 60); nothing else changed, so `metadata` still matches the advisories.
- `pnpm-12.5.1-clean.json`: a probe project whose only dependency is `is-number@7.0.0`, as written.
  A clean run is an empty `advisories` with zero counts.
- `pnpm-12.5.1-multi-version.json`: a probe project depending on `braces@3.0.2` and
  `micromatch@3.1.10` (which pulls in `braces@2.3.2`), as written. Each braces advisory lists both
  versions under one advisory, and `metadata` counts it once.
- `pnpm-12.5.1-ignored.json`: the same probe with `auditConfig.ignoreGhsas: [GHSA-grv7-fg5c-xmjg]`
  in its `pnpm-workspace.yaml`, as written. pnpm leaves that advisory out of `advisories` but still
  counts it in `metadata` (`high: 2`, one high advisory listed), so the gate fails the report
  (CI-SEC-005): `security/accepted-risks.yaml` is the only exception path (C-12.3).

When pnpm 12.5.1 cannot get an answer from the registry's audit endpoint (connection refused,
an HTTP error status, or a body that is not JSON) it exits 1, prints
`ERR_PNPM_AUDIT_BAD_RESPONSE` on stderr and writes nothing to stdout. The step's report is then
an empty file, which the gate fails (CI-SEC-005); the tests write that file themselves.

pnpm builds the report itself from the advisories that endpoint returns, so an answer listing
none gives a report like `pnpm-12.5.1-clean.json`. A clean report is only as complete as the
registry's answer: the gate cannot tell a registry that listed none from a tree with none. The
`dependabot-alerts` step (#3558, `../dependabot-alerts/README.md`) is the second signal.
