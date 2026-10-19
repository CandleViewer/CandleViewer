# Container image pin ledger

Digests are real registry manifest (index) digests, resolved anonymously over the registry v2 HTTP
API by `tools/ci/resolve_image_digests.py` (on each row's date) and verified in CI with `--check`
(#1857, fixes #1538 #1586). `--check` also enforces this ledger (#3571, CI-IMG-007..009): each
row's image, tag and digest must match a pin in the Dockerfiles, compose files or workflows the
script scans, each of those pins needs exactly one row, and the "All N pins" line must count the
rows; `--check --offline` checks the ledger alone, with no registry call. Refresh: edit the tag,
replace the digest with any placeholder, run the script without flags, then copy the new digest
into its row here.

| Image                      | Tag               | Digest                                                                  | Registry   | Resolved on | Source                                                 |
| -------------------------- | ----------------- | ----------------------------------------------------------------------- | ---------- | ----------- | ------------------------------------------------------ |
| postgres                   | 16.4              | sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412 | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| questdb/questdb            | 8.1.1             | sha256:82ef61a3919f4014e2aae1216f2803288b176a54c197d0933863bdc8c04a2e03 | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| prom/prometheus            | v2.54.1           | sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94 | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| python                     | 3.12.7-alpine3.20 | sha256:5049c050bdc68575a10bcb1885baa0689b6c15152d8a56a7e399fb49f783bf98 | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| prom/alertmanager          | v0.27.0           | sha256:e13b6ed5cb929eeaee733479dce55e10eb3bc2e9c4586c705a4e8da41e5eacf5 | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| prom/pushgateway           | v1.9.0            | sha256:98a458415f8f5afcfd45622d289a0aa67063563bec0f90d598ebc76783571936 | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| grafana/grafana            | 11.2.0            | sha256:408afb9726de5122b00a2576763a8a57a3c86d5b0eff5305bc994ceb3eb96c3f | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| bitnamilegacy/minio        | 2024.9.13         | sha256:8a92f71856f4b4b5755fa6afe4e7f9d0db7e18c889318f6772cb342d9b13470d | Docker Hub | 2026-10-06  | `infra/compose/docker-compose.yml`                     |
| python                     | 3.12-slim         | sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 | Docker Hub | 2026-10-18  | `infra/images/Dockerfile.api` (builder/runtime stages) |
| ghcr.io/zaproxy/zaproxy    | 2.17.0            | sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef | ghcr.io    | 2026-10-06  | `.github/workflows/dast-auth-zap.yml`                  |
| trufflesecurity/trufflehog | 3.97.9            | sha256:52e67fef4d054ecff5c2ce4b4ae376626d1ef54aa0898b53cac19c25e92e14db | Docker Hub | 2026-10-06  | `.github/workflows/_job-security.yml`, `pr.yml`        |
| zricethezav/gitleaks       | v8.30.1           | sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f | Docker Hub | 2026-10-18  | `.github/workflows/pr.yml`                             |

All 12 pins are verified present in their registry by `--check` (with 3x backoff retry on 429/5xx).

minio: `minio/minio:RELEASE.2024-09-13T20-26-02Z` is no longer anonymously served on Docker Hub or
quay.io (#1586). Nearest published equivalent is the same-date build `bitnamilegacy/minio:2024.9.13`
(data dir `/bitnami/minio/data`, console port via `MINIO_CONSOLE_PORT_NUMBER`).
