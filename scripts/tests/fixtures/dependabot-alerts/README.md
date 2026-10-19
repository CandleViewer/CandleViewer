# Recorded Dependabot alert listings (#3558)

`test_dependabot_alert_gate.py` runs these files through `tools/ci/security_gate.py --tool
dependabot`, the gate of `pr.yml`'s `dependabot-alerts` job: C-9.1 #11's Dependabot alert gate.
Its gate step runs
`gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/dependabot/alerts?state=open&per_page=100"`
with the job token, which `vulnerability-alerts: read` lets list the alerts. `--slurp` writes one
JSON array holding each page's array of alerts; with no open alerts it writes `[[]]`. Recorded
2026-10-18 with gh 2.67.0 (REST API version 2022-11-28). gh writes compact JSON with no final
newline; `.prettierignore` keeps the files that way.

- `gh-2.67.0-main.json`: the open alerts on `main` d61631fa6, one page: alert 55 (tauri 2.1.1 in
  the bench harness's `Cargo.toml`) and alerts 35, 37, 41, 43, 45, 47 and 49 (vitest on seven
  `package.json` files), all Medium. Trimmed to the fields the gate reads or the register's
  reasons cite: `number`, `state`, `dependency` (package, manifest path, scope, relationship),
  `security_advisory` (GHSA id, summary, severity), `security_vulnerability` (package, severity,
  vulnerable range, first patched version) and `html_url`. The advisories' descriptions,
  references and scores and the alerts' timestamps are left out. The tests plant an alert at High
  or Critical, on another package or manifest, or with another vulnerable range, from these
  records.
- `gh-2.67.0-not-found.json`: what gh wrote, then exiting 1, for a repository path that does not
  exist: an API error inside the slurp array. A token without the permission gets the same shape
  with another message and status. The step fails on gh's exit status (CI-SEC-005), and the gate
  fails this body too.

Redaction (C-13.5): none was needed. The kept fields hold no credential, token or user (the API's
user fields, such as `dismissed_by`, are among those left out), and `html_url` is the alert's page
in this public repository.

The alerts describe the default branch, not the PR under test: the gate judges a blocking one on
the PR's tree against its merge base with `main` (`docs/ci-runbook.md`, CI-SEC-001).
