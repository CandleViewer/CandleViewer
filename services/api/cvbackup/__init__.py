"""The backup sidecar (ADR-0041 section 1, #3319), a sibling of `candleviewer`.

A separate process in its own container and image (`infra/images/Dockerfile.backup`, #3319 B1c),
which alone carries the Postgres client tools and the age implementation. It runs, verifies and
removes backup artefacts at the API's request over a local Unix socket
(`docs/plan/24-internal-schemas.md` §15.8) and records nothing in Postgres: the E42-T05 services
in `candleviewer.admin.backups` record every step.

It imports no `candleviewer` module and `candleviewer` imports none of it, and it imports none of
the API's third-party packages (the `independence-backup-sidecar` and
`forbidden-cvbackup-thirdparty` contracts of `services/api/.importlinter`): the standard library
only. The wheel packages only `candleviewer`, the sdist excludes this package
(`services/api/pyproject.toml`), and `infra/images/Dockerfile.api` copies only `candleviewer`, so
the API image never carries it.

Modules (#3319 B1b): `config`, `protocol` (the §15.8 codec), `server` (the socket), `paths`
(confinement on the backup volume), `ledger` (its own run record), `floor` (the rules no request
lifts), `ops` (plan, verify, remove; run and restore answer until B1c and B2) and `age_format`
(the recipient fingerprint and the header check, no decryption). The run path (child processes,
the age tool, the dump kinds) is B1c.
"""
